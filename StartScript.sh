#!/bin/bash
cd /home/zorn/bz2-watchbot/
python3 -m venv venv
exec bash --rcfile <(echo '. ~/.bashrc; source venv/bin/activate; python3 main.py')
