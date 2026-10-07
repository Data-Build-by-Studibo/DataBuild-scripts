# -*- coding: utf-8 -*-
 
#-----------------------IMPORTS-------------------------------------------------------
 
import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import (TaskDialog, TaskDialogCommandLinkId,
                               TaskDialogCommonButtons, TaskDialogResult)
 
# Onze eigen plugin-assembly (DataBuild.dll) - wordt al geladen door PythonRunner.cs
clr.AddReference("DataBuild")
from DataBuild.Core import ScriptDownloader, GitHubConfig
 
# WPF (geen WinForms!) voor het keuzevenster
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
from System.Windows.Markup import XamlReader
from System.IO import Path
 
 
FAMILY_PICKER_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Data Build - Familie laden"
        Height="420" Width="600"
        WindowStartupLocation="CenterScreen"
        ResizeMode="CanResize">
    <DockPanel Margin="14">
        <TextBlock DockPanel.Dock="Top"
                   Text="Kies een familie uit de Data Build-bibliotheek:"
                   FontWeight="Bold" Margin="0,0,0,10"/>
        <StackPanel DockPanel.Dock="Bottom" Orientation="Horizontal"
                    HorizontalAlignment="Right" Margin="0,12,0,0">
            <Button x:Name="OkButton" Content="Laden" Width="100" Height="28" Margin="0,0,8,0"/>
            <Button x:Name="CancelButton" Content="Annuleren" Width="100" Height="28"/>
        </StackPanel>
        <ListBox x:Name="FamilyListBox" />
    </DockPanel>
</Window>
"""
 
 
#-----------------------FAMILY LOAD OPTIONS-------------------------------------------
 
class DataBuildFamilyLoadOptions(IFamilyLoadOptions):
    """Wordt door Revit aangeroepen als de familie al in het project zit.
    Return True = overschrijven. overwrite_params bepaalt of de
    parameterwaarden van bestaande types ook overschreven worden."""
 
    def __init__(self, overwrite_params):
        self.overwrite_params = overwrite_params
 
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = self.overwrite_params
        return True
 
    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        # Geneste shared families: neem de versie uit het geladen bestand
        source.Value = FamilySource.Family
        overwriteParameterValues.Value = self.overwrite_params
        return True
 
 
#-----------------------FUNCTIES------------------------------------------------------
 
def choose_family(family_names):
    """Toont het keuzevenster en geeft de gekozen bestandsnaam terug (of None)."""
    window = XamlReader.Parse(FAMILY_PICKER_XAML)
    list_box = window.FindName("FamilyListBox")
    ok_button = window.FindName("OkButton")
    cancel_button = window.FindName("CancelButton")
 
    for name in family_names:
        list_box.Items.Add(name)
    if list_box.Items.Count > 0:
        list_box.SelectedIndex = 0
 
    selection = {"name": None}
 
    def on_ok(sender, args):
        if list_box.SelectedItem is not None:
            selection["name"] = str(list_box.SelectedItem)
        window.DialogResult = True
        window.Close()
 
    def on_cancel(sender, args):
        window.DialogResult = False
        window.Close()
 
    ok_button.Click += on_ok
    cancel_button.Click += on_cancel
    list_box.MouseDoubleClick += on_ok
 
    dialog_result = window.ShowDialog()
 
    if dialog_result:
        return selection["name"]
    return None
 
 
def family_exists(doc, family_name):
    """Kijkt of er al een familie met deze naam in het project zit."""
    for fam in FilteredElementCollector(doc).OfClass(Family):
        if fam.Name == family_name:
            return True
    return False
 
 
def ask_overwrite(family_name):
    """Vraagt wat er moet gebeuren met een bestaande familie.
    Geeft 'all', 'keep_values' of None (annuleren) terug."""
    td = TaskDialog("Data Build")
    td.MainInstruction = "Familie '{0}' bestaat al in dit project.".format(family_name)
    td.MainContent = ("Wil je de huidige versie overschrijven met de laatste versie "
                      "uit de Data Build-bibliotheek?")
    td.AddCommandLink(
        TaskDialogCommandLinkId.CommandLink1,
        "Overschrijven",
        "Laatste versie laden. Ook de parameterwaarden van bestaande types "
        "worden vervangen door die uit de bibliotheek."
    )
    td.AddCommandLink(
        TaskDialogCommandLinkId.CommandLink2,
        "Overschrijven, parameterwaarden behouden",
        "Geometrie en nieuwe parameters bijwerken, maar de waarden die "
        "in het project zijn ingevuld blijven staan."
    )
    td.CommonButtons = TaskDialogCommonButtons.Cancel
    td.DefaultButton = TaskDialogResult.CommandLink1
 
    result = td.Show()
    if result == TaskDialogResult.CommandLink1:
        return "all"
    if result == TaskDialogResult.CommandLink2:
        return "keep_values"
    return None
 
 
#-----------------------HOOFDPROGRAMMA-------------------------------------------------
 
uiapp = __revit__
doc = uiapp.ActiveUIDocument.Document
 
family_names = list(ScriptDownloader.ListGitHubFamilies(GitHubConfig.FamiliesFolderRelativePath))
 
if not family_names:
    TaskDialog.Show(
        "Data Build",
        "Geen familiebestanden (.rfa) gevonden in de 'Families'-map op GitHub,\n"
        "of de map kon niet bereikt worden (controleer je internetverbinding)."
    )
else:
    chosen_name = choose_family(family_names)
 
    if chosen_name is not None:
        # Revit gebruikt de bestandsnaam zonder .rfa als familienaam
        family_name = Path.GetFileNameWithoutExtension(chosen_name)
 
        already_loaded = family_exists(doc, family_name)
        overwrite_params = True
        proceed = True
 
        if already_loaded:
            choice = ask_overwrite(family_name)
            if choice is None:
                proceed = False  # gebruiker heeft geannuleerd
            else:
                overwrite_params = (choice == "all")
 
        if proceed:
            t = Transaction(doc, "Familie laden: {0}".format(family_name))
            try:
                # Pas downloaden nadat de gebruiker gekozen heeft
                local_path = ScriptDownloader.DownloadBinaryToLocalFile(
                    GitHubConfig.GetFamilyRelativePath(chosen_name)
                )
 
                t.Start()
                family_ref = clr.Reference[Family]()
                options = DataBuildFamilyLoadOptions(overwrite_params)
                loaded = doc.LoadFamily(local_path, options, family_ref)
                t.Commit()
 
                if loaded and already_loaded:
                    message = "Familie '{0}' is overschreven met de laatste versie.".format(family_name)
                elif loaded:
                    message = "Familie '{0}' is succesvol geladen in het project.".format(family_name)
                elif already_loaded:
                    message = ("Familie '{0}' is niet gewijzigd.\n"
                               "De versie in het project is waarschijnlijk al gelijk "
                               "aan die in de bibliotheek.").format(family_name)
                else:
                    message = "Familie '{0}' kon niet geladen worden.".format(family_name)
 
                TaskDialog.Show("Data Build", message)
 
            except Exception as e:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                TaskDialog.Show(
                    "Data Build - Scriptfout",
                    "Kon de familie niet downloaden/laden:\n{0}".format(str(e))
                )
 


