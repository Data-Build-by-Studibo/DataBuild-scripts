# -*- coding: utf-8 -*-
# ================================================================
# DIAGNOSTISCHE VERSIE - tijdelijk, enkel om te zien waar het vastloopt.
# Elke stap toont een eigen venstertje ("Checkpoint N"). Klik telkens op
# "Sluiten" om naar de volgende stap te gaan. Meld aan Claude tot welk
# checkpoint-nummer je geraakt (of welke foutmelding je krijgt).
# ================================================================

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.UI import TaskDialog

TaskDialog.Show("Data Build - Debug", "Checkpoint 1: script is gestart, RevitAPI/RevitAPIUI geladen.")

from Autodesk.Revit.DB import *
TaskDialog.Show("Data Build - Debug", "Checkpoint 2: Autodesk.Revit.DB geimporteerd.")

from Autodesk.Revit.UI import FileOpenDialog, ItemSelectionDialogResult
TaskDialog.Show("Data Build - Debug", "Checkpoint 3: FileOpenDialog/ItemSelectionDialogResult geimporteerd.")

from System.Collections.Generic import List
TaskDialog.Show("Data Build - Debug", "Checkpoint 4: System.Collections.Generic geimporteerd.")

import zipfile
TaskDialog.Show("Data Build - Debug", "Checkpoint 5: zipfile geimporteerd.")

import re
import xml.etree.ElementTree as ET
TaskDialog.Show("Data Build - Debug", "Checkpoint 6: re + xml.etree.ElementTree geimporteerd.")

uiapp = __revit__
TaskDialog.Show("Data Build - Debug", "Checkpoint 7: __revit__ opgehaald.")

uidoc = uiapp.ActiveUIDocument
doc = uidoc.Document
TaskDialog.Show("Data Build - Debug", "Checkpoint 8: actief document = {0}".format(doc.Title))

file_dialog = FileOpenDialog("Excel bestanden (*.xlsx)|*.xlsx")
TaskDialog.Show("Data Build - Debug", "Checkpoint 9: FileOpenDialog-object aangemaakt.")

file_dialog.Title = "Selecteer een Excel-bestand om gegevens te importeren"
TaskDialog.Show("Data Build - Debug", "Checkpoint 10: titel ingesteld. Het bestandsvenster wordt nu geopend...")

dialog_result = file_dialog.Show()
TaskDialog.Show("Data Build - Debug", "Checkpoint 11: bestandsvenster gesloten. Resultaat = {0}".format(dialog_result))

if dialog_result != ItemSelectionDialogResult.Confirmed:
    TaskDialog.Show("Data Build - Debug", "Geen bestand gekozen (of geannuleerd). Script stopt hier normaal.")
else:
    model_path = file_dialog.GetSelectedModelPath()
    excel_file_path = ModelPathUtils.ConvertModelPathToUserVisiblePath(model_path)
    TaskDialog.Show("Data Build - Debug", "Checkpoint 12: geselecteerd bestand = {0}".format(excel_file_path))

TaskDialog.Show("Data Build - Debug", "EINDE: het volledige script is doorlopen zonder crash.")
