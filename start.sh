#!/bin/bash

# Lancer main.py en arrière-plan
python main.py &

# Lancer dashboard.py au premier plan
python dashboard.py
