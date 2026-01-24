#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""  """
from json_repair import repair_json
class Json:

    def __init__(self):
        ...




if __name__ == '__main__':
    print(repair_json("desayuno=no,parking=no,facture=no"))
    print(repair_json("desayuno=no, parking=si"))
    print(repair_json('"{ "breakfast":False, "parking":True }"'))
    print(repair_json('desayuno=si\nparqueadero=no\nobservaciones=ninguna'))