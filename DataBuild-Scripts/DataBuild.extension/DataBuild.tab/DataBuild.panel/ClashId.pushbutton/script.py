# -*- coding: utf-8 -*-
 
__title__ = "ClashOverview"
__author__ = "Sean De Gent"
__doc__ = """Version = 1.4
Date    = 22-09-26
_____________________________________________________________________
Description:
 
O.b.v. de geselecteerde excel-file, zal men elementen zichtbaar maken die in conflict zijn.
_____________________________________________________________
Last update:
 
- [22-09-26] 1.4 Definitieve versie op basis van de bevestigd werkende structuur:
                  module-niveau code (geen def main()), Revit's eigen
                  FileOpenDialog + TaskDialog (geen WinForms).
- [19-09-23] 1.0 RELEASE
 
author  = Sean De Gent i.o.v. BimPlan
_____________________________________________________________________
"""
 
#-----------------------IMPORTS-------------------------------------------------------
 
import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import TaskDialog, FileOpenDialog, ItemSelectionDialogResult
from System.Collections.Generic import List
 
import zipfile
import re
import xml.etree.ElementTree as ET
 
NS = {
    'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'rel': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}
 
 
def _split_cell_ref(ref):
    m = re.match(r'([A-Z]+)(\d+)', ref)
    return m.group(1), int(m.group(2))
 
 
def read_xlsx_column(path, sheet_name, column_letter, start_row):
    with zipfile.ZipFile(path) as z:
        wb_xml = ET.fromstring(z.read('xl/workbook.xml'))
        sheet_rid = None
        for sheet in wb_xml.find('main:sheets', NS):
            if sheet.get('name') == sheet_name:
                sheet_rid = sheet.get('{%s}id' % NS['rel'])
                break
        if sheet_rid is None:
            raise Exception("Tabblad '{0}' niet gevonden in de excel.".format(sheet_name))
 
        rels_xml = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        sheet_target = None
        for rel in rels_xml:
            if rel.get('Id') == sheet_rid:
                sheet_target = rel.get('Target')
                break
        if sheet_target is None:
            raise Exception("Kon het tabblad-bestand niet terugvinden in de excel.")
 
        sheet_path = sheet_target if sheet_target.startswith('xl/') else 'xl/' + sheet_target
        sheet_xml = ET.fromstring(z.read(sheet_path))
 
        shared_strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            ss_xml = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in ss_xml.findall('main:si', NS):
                texts = si.findall('.//main:t', NS)
                shared_strings.append(''.join(t.text or '' for t in texts))
 
        values = []
        sheet_data = sheet_xml.find('main:sheetData', NS)
        for row in sheet_data:
            row_num = int(row.get('r'))
            if row_num < start_row:
                continue
            for cell in row:
                ref = cell.get('r')
                col, _ = _split_cell_ref(ref)
                if col != column_letter:
                    continue
                v = cell.find('main:v', NS)
                if v is None or v.text is None:
                    continue
                if cell.get('t') == 's':
                    values.append(shared_strings[int(v.text)])
                else:
                    values.append(v.text)
    return values
 
 
#-----------------------HOOFDPROGRAMMA-------------------------------------------------
 
uiapp = __revit__
uidoc = uiapp.ActiveUIDocument
doc = uidoc.Document
 
file_dialog = FileOpenDialog("Excel bestanden (*.xlsx)|*.xlsx")
file_dialog.Title = "Selecteer een Excel-bestand om gegevens te importeren"
dialog_result = file_dialog.Show()
 
if dialog_result != ItemSelectionDialogResult.Confirmed:
    TaskDialog.Show("Data Build", "Geen bestand geselecteerd. Het script wordt afgebroken.")
else:
    model_path = file_dialog.GetSelectedModelPath()
    excel_file_path = ModelPathUtils.ConvertModelPathToUserVisiblePath(model_path)
 
    try:
        # Kolom C = 3de kolom, rijen vanaf 2 (rij 1 = headers)
        raw_values = read_xlsx_column(excel_file_path, "ID to Revit", "C", 2)
        ids_to_show = [ElementId(int(float(v))) for v in raw_values]
 
        all_elements = FilteredElementCollector(doc, uidoc.ActiveView.Id).ToElementIds()
        ids_to_hide = [id for id in all_elements if id not in ids_to_show]
 
        t = Transaction(doc, "Tijdelijk elementen verbergen")
        t.Start()
 
        elements_to_hide_collection = List[ElementId]()
        current_view = uidoc.ActiveView
 
        for id in ids_to_hide:
            element = doc.GetElement(id)
            if element.CanBeHidden(current_view):
                elements_to_hide_collection.Add(id)
 
        current_view.HideElementsTemporary(elements_to_hide_collection)
        t.Commit()
 
        TaskDialog.Show(
            "Data Build",
            "Klaar! {0} elementen tijdelijk verborgen ({1} zichtbaar gehouden).".format(
                elements_to_hide_collection.Count, len(ids_to_show)
            )
        )
 
    except Exception as e:
        TaskDialog.Show("Data Build - Scriptfout", "Fout bij het importeren van gegevens:\n{0}".format(str(e)))
 
