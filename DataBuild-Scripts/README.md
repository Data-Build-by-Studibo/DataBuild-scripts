# DataBuild-Scripts

Deze repo bevat alle python-scripts van de **Data Build** Revit-plugin, opgebouwd
volgens een boomstructuur (vergelijkbaar met pyRevit):

```
DataBuild.extension/
  DataBuild.tab/
    DataBuild.panel/
      Script.pushbutton/
        script.py       <- de eigenlijke python-code
        bundle.yaml      <- titel/tooltip (optioneel, voor later gebruik)
```

- **.extension** = de hele plugin-inhoud
- **.tab** = een tabblad in het Revit-lint
- **.panel** = een paneel binnen dat tabblad
- **.pushbutton** = één knop, met zijn eigen `script.py`

De C#-plugin downloadt `script.py` rechtstreeks via de GitHub *raw* URL:

```
https://raw.githubusercontent.com/<gebruiker>/DataBuild-Scripts/main/DataBuild.extension/DataBuild.tab/DataBuild.panel/TestScript.pushbutton/script.py
```

Nieuwe knoppen toevoegen = gewoon een nieuwe `.pushbutton`-map aanmaken met een `script.py`.
