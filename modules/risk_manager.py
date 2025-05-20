# modules/risk_manager.py
import logging
from modules.positions_store import save_state # Inchangé

# NOUVELLE CONSTANTE: Valeur minimale en USDC pour qu'un actif non suivi soit ajouté à positions_meta
MIN_VALUE_TO_ADD_TO_META = 1.0  # Par exemple, 1 USDC. Ajustez si nécessaire.

def intraday_check_real(state, bexec, config):
    """
    Lecture du compte => stop-loss, partial-take-profit, trailing ...
    Et on initialise entry_px=current_px si absent de positions_meta,
    MAIS seulement si la valeur de l'actif est suffisante pour les nouveaux tokens.
    """
    logging.info("[INTRADAY] Starting intraday_check_real")
    strat = config["strategy"]

    try:
        account_info = bexec.client.get_account()
    except Exception as e:
        logging.error(f"[INTRADAY] get_account error => {e}")
        return

    balances = account_info.get("balances", []) # Utiliser .get pour éviter KeyError si "balances" manque
    if not balances:
        logging.warning("[INTRADAY] No balances found in account_info.")
        return
        
    holdings = {}
    for b in balances:
        asset = b["asset"]
        try:
            free  = float(b.get("free", 0.0)) # Utiliser .get pour robustesse
            locked= float(b.get("locked", 0.0))
        except ValueError:
            logging.warning(f"[INTRADAY] Could not parse free/locked for asset {asset}. Skipping.")
            continue
            
        qty   = free + locked
        # on ignore USDC= stable
        if qty > 0 and asset.upper() != "USDC":
            holdings[asset] = qty

    logging.info(f"[INTRADAY] Found holdings (qty > 0, not USDC): {holdings}")

    for asset, real_qty in holdings.items():
        current_px = bexec.get_symbol_price(asset) # Peut retourner 0.0 si la paire XXXUSDC n'existe pas

        # MODIFICATION: Calculer la valeur actuelle de l'actif pour la condition d'ajout
        current_value_of_asset = current_px * real_qty

        # -- Si le token n'existe pas dans positions_meta => on l'ajoute sous condition de valeur --
        if asset not in state.get("positions_meta", {}): # Utiliser .get pour robustesse
            # NOUVELLE CONDITION: Ajouter uniquement si la valeur est suffisante
            if current_value_of_asset >= MIN_VALUE_TO_ADD_TO_META:
                state.setdefault("positions_meta", {})[asset] = { # setdefault est plus sûr
                    "entry_px": current_px,
                    "did_skip_sell_once": False,
                    "partial_sold": False,
                    "max_price": current_px  # Initialiser max_price avec le prix d'entrée
                }
                save_state(state)
                logging.info(f"[INTRADAY] Added '{asset}' to positions_meta (value: {current_value_of_asset:.2f} USDC, price: {current_px:.4f})")
                # Pour la suite de la logique dans CET appel, initialiser entry_px et ratio
                entry_px = current_px
                ratio = 1.0 # Car c'est une nouvelle position, PNL est 0%
            else:
                logging.info(f"[INTRADAY] Skipping add of '{asset}' to positions_meta, its current value ({current_value_of_asset:.2f} USDC) is less than MIN_VALUE_TO_ADD_TO_META ({MIN_VALUE_TO_ADD_TO_META:.2f} USDC). Price found: {current_px:.4f}.")
                continue # Ne pas traiter ce token davantage dans cette passe s'il n'est pas ajouté
        else:
            # Le token est déjà dans positions_meta, récupérer ses informations
            meta = state["positions_meta"][asset]
            entry_px = meta.get("entry_px", 0.0)
            if entry_px <= 0.0: # Si entry_px est 0 ou invalide pour une raison quelconque
                # Mettre à jour entry_px avec le prix actuel s'il est valide
                # Et s'assurer que max_price est aussi mis à jour
                if current_px > 0: # Ne pas mettre à jour avec un prix nul
                    meta["entry_px"] = current_px
                    meta["max_price"] = max(meta.get("max_price", current_px), current_px) # Conserver le max_price existant s'il est plus élevé
                    state["positions_meta"][asset] = meta
                    save_state(state)
                    logging.info(f"[INTRADAY] Updated invalid entry_px for '{asset}' to {current_px:.4f}.")
                    entry_px = current_px # Utiliser le prix mis à jour pour le calcul du ratio
                else: # Si le prix actuel est aussi 0, on ne peut pas calculer de ratio
                    logging.warning(f"[INTRADAY] Cannot calculate ratio for '{asset}', entry_px is {entry_px} and current_px is {current_px}.")
                    continue # Passer au token suivant

            # Calcul du ratio PNL
            if entry_px > 0: # S'assurer que entry_px est valide pour éviter DivisionByZero
                ratio = current_px / entry_px
            else: # Ne devrait pas arriver si la logique ci-dessus est correcte, mais sécurité
                ratio = 1.0 


        logging.info(
            f"[INTRADAY CHECK] {asset} => Ratio: {ratio:.3f}, "
            f"Entry Px: {entry_px:.4f}, Current Px: {current_px:.4f}, Qty: {real_qty}"
        )

        # Si current_px est 0, la plupart des logiques de trading ne s'appliqueront pas ou pourraient mal se comporter.
        # Cela peut arriver si la paire XXXUSDC n'existe plus.
        if current_px <= 0:
            logging.warning(f"[INTRADAY] Current price for {asset} is {current_px:.4f}. Skipping trading logic (SL/TP/Trailing). Consider manual review if position value was significant.")
            # On ne fait pas 'continue' ici pour permettre le nettoyage de 'positions_meta' plus bas si le token n'est plus dans 'holdings'
            # (bien que dans ce cas, il est dans holdings mais avec un prix nul).
            # Si le token n'a plus de prix, il ne sera pas vendu par les logiques ci-dessous car val_in_usd sera 0.
            # La logique de `daily_update_live` pourrait le vendre si `prob < sell_threshold` et `val_in_usd > MIN_VALUE_TO_SELL` (ce qui ne sera pas le cas si prix=0).


        # STOP-LOSS (inchangé)
        # S'assurer que entry_px est positif pour éviter des actions sur des données invalides
        if entry_px > 0 and ratio <= (1 - strat["stop_loss_pct"]):
            logging.info(f"[INTRADAY STOPLOSS] {asset}, ratio={ratio:.2f} <= {(1 - strat['stop_loss_pct']):.2f}")
            sold_val = bexec.sell_all(asset, real_qty)
            logging.info(f"[INTRADAY STOPLOSS] => {asset} sold, value={sold_val:.2f} USDC")
            if asset in state.get("positions_meta", {}): # Vérifier avant de supprimer
                del state["positions_meta"][asset]
            save_state(state)
            continue # Token vendu, passer au suivant

        # PARTIAL TAKE PROFIT (inchangé)
        # S'assurer que entry_px est positif
        if entry_px > 0 and ratio >= (1 + strat["partial_take_profit_pct"]) and \
           not state.get("positions_meta", {}).get(asset, {}).get("partial_sold", False):
            qty_to_sell = real_qty * strat["partial_take_profit_ratio"]
            partial_val = bexec.sell_partial(asset, qty_to_sell) # sell_partial appelle sell_all
            if asset in state.get("positions_meta", {}): # S'assurer que le token est toujours là
                 state["positions_meta"][asset]["partial_sold"] = True
                 save_state(state)
                 logging.info(f"[INTRADAY PARTIAL SELL] {asset}, ratio={ratio:.2f}, partial_val={partial_val:.2f} USDC")
            else: # Devrait être rare, mais si le token a été vendu entre-temps (ex: par stop-loss simultané)
                 logging.warning(f"[INTRADAY PARTIAL SELL] {asset} not found in positions_meta after attempting partial sell. Value: {partial_val:.2f} USDC")


        # TRAILING STOP (inchangé, mais avec vérifications additionnelles)
        # S'assurer que entry_px est positif
        if entry_px > 0 and ratio >= strat["trailing_trigger_pct"]:
            # S'assurer que l'asset est toujours dans positions_meta avant d'y accéder
            if asset in state.get("positions_meta", {}):
                meta_trailing = state["positions_meta"][asset] # Récupérer la dernière version de meta
                current_max_price = meta_trailing.get("max_price", entry_px) # Utiliser entry_px comme fallback pour max_price

                if current_px > current_max_price:
                    meta_trailing["max_price"] = current_px
                    state["positions_meta"][asset] = meta_trailing # Réassigner pour être sûr
                    save_state(state)
                    logging.info(f"[INTRADAY TRAILING] New max price for {asset} => {current_px:.4f} (updated from {current_max_price:.4f})")
                    current_max_price = current_px # Mettre à jour la variable locale

                # Vérifier si le stop du trailing est touché
                if current_max_price > 0 and current_px <= current_max_price * (1 - strat["trailing_pct"]):
                    logging.info(f"[INTRADAY TRAILING STOP] {asset}, current_px {current_px:.4f} <= max_price {current_max_price:.4f} * (1 - {strat['trailing_pct']})")
                    sold_val = bexec.sell_all(asset, real_qty)
                    logging.info(f"[INTRADAY TRAILING STOP] => {asset} sold, value={sold_val:.2f} USDC")
                    if asset in state.get("positions_meta", {}): # Revérifier avant de supprimer
                        del state["positions_meta"][asset]
                    save_state(state)
                    continue # Token vendu, passer au suivant
            else:
                logging.warning(f"[INTRADAY TRAILING] {asset} was in holdings but disappeared from positions_meta before trailing logic.")


    # Nettoyage de positions_meta si un token n'est plus dans les holdings (inchangé)
    # Il est important que cela se fasse après la boucle pour ne pas modifier le dictionnaire sur lequel on itère (bien que `list(state["positions_meta"].keys())` mitige cela)
    # Faire une copie des clés pour itération sûre
    assets_in_meta = list(state.get("positions_meta", {}).keys())
    for asset_meta_key in assets_in_meta:
        if asset_meta_key not in holdings:
            # S'assurer que la clé existe toujours avant de la supprimer (au cas où une opération asynchrone l'aurait déjà fait)
            if asset_meta_key in state.get("positions_meta", {}):
                del state["positions_meta"][asset_meta_key]
                logging.info(f"[INTRADAY CLEAN META] Removed {asset_meta_key} from positions_meta, not in current holdings.")
                save_state(state) # Sauvegarder après chaque suppression ou une fois après la boucle de nettoyage

    logging.info("[INTRADAY] Intraday check_real finished.")