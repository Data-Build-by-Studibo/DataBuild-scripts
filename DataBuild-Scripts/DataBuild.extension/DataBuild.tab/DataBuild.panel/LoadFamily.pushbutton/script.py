# -*- coding: utf-8 -*-

#-----------------------IMPORTS-------------------------------------------------------

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import TaskDialog

# Onze eigen plugin-assembly (DataBuild.dll) - wordt al geladen door PythonRunner.cs
clr.AddReference("DataBuild")
from DataBuild.Core import ScriptDownloader, GitHubConfig

# WPF (geen WinForms!) voor het keuzevenster
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
from System.Windows.Markup import XamlReader


FAMILY_PICKER_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Data Build - Familie laden"
        Height="420" Width="380"
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

    if chosen_name is None:
        pass  # gebruiker heeft geannuleerd - niets doen
    else:
        try:
            local_path = ScriptDownloader.DownloadBinaryToLocalFile(
                GitHubConfig.GetFamilyRelativePath(chosen_name)
            )

            t = Transaction(doc, "Familie laden: {0}".format(chosen_name))
            t.Start()

            family_ref = clr.Reference[Family]()
            loaded = doc.LoadFamily(local_path, family_ref)

            t.Commit()

            if loaded:
                TaskDialog.Show(
                    "Data Build",
                    "Familie '{0}' is succesvol geladen in het project.".format(chosen_name)
                )
            else:
                TaskDialog.Show(
                    "Data Build",
                    "Familie '{0}' was al aanwezig in het project (of kon niet geladen worden).".format(chosen_name)
                )

        except Exception as e:
            TaskDialog.Show(
                "Data Build - Scriptfout",
                "Kon de familie niet downloaden/laden:\n{0}".format(str(e))
            )
