# -*- coding: utf-8 -*-

from Autodesk.Revit.UI import TaskDialog

uiapp = __revit__
uidoc = uiapp.ActiveUIDocument
doc = uidoc.Document if uidoc else None

message = "Data Build plugin werkt!\n\n"
if doc:
    message += "Actief document: {}\n".format(doc.Title)
    message += "Revit versie: {}".format(uiapp.Application.VersionNumber)
else:
    message += "Geen actief document open."

TaskDialog.Show("Data Build - Test", message)
