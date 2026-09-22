# -*- coding: utf-8 -*-

__title__ = "ClashOverview"
__author__ = "Sean De Gent"
__doc__ = """Version = 1.0
Date    = 19-09-23
_____________________________________________________________________
Description:

O.b.v. de geselecteerde excel-file, zal men elementen zichtbaar maken de in conflict zijn.
_____________________________________________________________
Last update:

- [19-09-23] 1.0 RELEASE


author  = Sean De Gent i.o.v. BimPlan

_____________________________________________________________________
"""

#-----------------------IMPORTS-------------------------------------------------------

import clr
clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import OpenFileDialog, DialogResult, MessageBox
import xlrd  # Gebruik xlrd om Excel-bestanden te lezen
from System.Collections.Generic import List
from System.Windows.Forms import OpenFileDialog, DialogResult, MessageBox

# Importeren van Revit API-elementen
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *

def main():
    uidoc = __revit__.ActiveUIDocument
    doc = uidoc.Document

    # Vraag de gebruiker om het Excel-bestand te selecteren
    open_file_dialog = OpenFileDialog()
    open_file_dialog.Filter = "Excel Files (*.xlsx)|*.xlsx"
    open_file_dialog.Title = "Selecteer een Excel-bestand om gegevens te importeren"
    result = open_file_dialog.ShowDialog()

    if result != DialogResult.OK:
        # Toon een foutmelding als er geen bestand is geselecteerd
        MessageBox.Show("Geen bestand geselecteerd. Het script wordt afgebroken.")
        return

    excel_file_path = open_file_dialog.FileName

    # Open het Excel-bestand en lees de gegevens van het tabblad "BPL_ID to RVT"
    try:
        workbook = xlrd.open_workbook(excel_file_path)
        worksheet = workbook.sheet_by_name("ID to Revit")  # Specificeer het tabblad

        # # Maak een lijst van element-ID's die zichtbaar moeten blijven
        ids_to_show = [ElementId(int(worksheet.cell_value(row_num, 2))) for row_num in range(1, worksheet.nrows)]


        # Verzamel alle elementen in de huidige weergave
        all_elements = FilteredElementCollector(doc, uidoc.ActiveView.Id).ToElementIds()

        # Maak een lijst van elementen die verborgen moeten worden door de elementen die zichtbaar moeten blijven uit de verzameling van alle elementen te verwijderen
        ids_to_hide = [id for id in all_elements if id not in ids_to_show]

        # Start een transactie om de zichtbaarheid van elementen aan te passen
        t = Transaction(doc, "Tijdelijk elementen verbergen")
        t.Start()

        # Converteer de Python-lijst naar een ICollection[ElementId]
        elements_to_hide_collection = List[ElementId]()

        # Verkrijg de huidige weergave
        current_view = uidoc.ActiveView

        for id in ids_to_hide:
            element = doc.GetElement(id)
            if element.CanBeHidden(current_view):
                elements_to_hide_collection.Add(id)
            else:
                # Hier kun je code toevoegen om een waarschuwing te geven of het niet-verbergbare element te loggen
                pass

        # Gebruik de HideElements methode van het View object om de elementen te verbergen
        current_view.HideElementsTemporary(elements_to_hide_collection)

        # Commit de transactie
        t.Commit()

    except Exception as e:
        # Toon een foutmelding als er een fout optreedt
        MessageBox.Show("Fout bij het importeren van gegevens: {0}".format(str(e)))

if __name__ == "__main__":
    main()
