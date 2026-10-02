# -*- coding: utf-8 -*-

import io
import json
import os
import re
import tempfile
 
import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System")
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
 
from System.Collections.Generic import List
from Autodesk.Revit import DB
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommandLinkId, TaskDialogResult
import System.Windows.Forms as WF
import System.Drawing as SD
 
BIC = DB.BuiltInCategory
TITLE = "Openings - Host + Nummering"
 
# --------------------------------------------------------------------------
CONFIG = {
    # Welke stappen uitvoeren
    "run_host_params": True,
    "run_numbering": True,
 
    # Sparingen in het actieve model
    "opening_category": BIC.OST_GenericModel,
    "opening_family_filter": "DBU_GM_UN_Opening",
 
    # ---- Gedeeld: stap 1 schrijft, stap 2 leest ----
    "param_host_category": "DBU_CTE_Opening Host Category",
 
    # ---- Stap 1: host- en Z-parameters ----
    "param_host_element": "DBU_CTE_Opening Host Element",
    "param_host_link": "DBU_CTE_Opening Host Link",
    "param_host_id": "DBU_CTE_Host ID",
    "param_z_top": "DBU_CTE_Z Value - Top",
    "param_z_center": "DBU_CTE_Z Value - Center",
    "rectangular_filter": "Rectangular",
    "param_height": "Element Height",
    "min_intersection_volume": 1e-4,   # ft3
    "clear_when_no_host": False,
 
    # ---- Stap 2: nummering ----
    "param_discipline": "DBU_CTE_Discipline",
    "param_level": "DBU_CTE_BuildingPart",
    "param_mark": "Mark",  # -> ingebouwde Mark-parameter
    "separator": "-",
    "numbered_regex": r"^[A-Za-z]+-.+-[A-Za-z]+-.+$",
    "number_position": 3,  # D-N-H-[3]
    "number_padding": 0,   # 0 = 1, 2, ...   3 = 001, 002, ...
 
    # Eerst samenvatting tonen en om bevestiging vragen
    "ask_confirmation": True,
}
 
# Rollen voor gelinkte modellen. De gebruiker kiest per rol welke link(s)
# erbij horen. 'hint' = tekst in de linknaam die de eerste keer automatisch
# aangevinkt wordt (daarna onthoudt het script de keuze per project).
ROLE_RULES = [
    {
        "role": "STRUCTURE",
        "label": "Structuurmodel(len)",
        "hint": ["STRUCTURE", "STAB", "STR"],
        "categories": [BIC.OST_Walls, BIC.OST_StructuralFraming,
                       BIC.OST_StructuralColumns, BIC.OST_StructuralFoundation,
                       BIC.OST_Floors],
        "exclude_type_name_contains": ["Secant"],
        "exclude_workset_contains": [],
    },
    {
        "role": "ARCHITECTURE",
        "label": "Architectuurmodel(len)",
        "hint": ["ARCHITECTURE", "ARCH", "ARC"],
        "categories": [BIC.OST_Walls, BIC.OST_StructuralFraming,
                       BIC.OST_StructuralColumns, BIC.OST_GenericModel],
        "exclude_type_name_contains": [],
        "exclude_workset_contains": [u"Stabilité"],
    },
]
 
# Hier wordt per project de laatste linkkeuze bewaard
MEMORY_FILE = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()),
                           "DataBuild", "openings_links.json")
 
CATEGORY_CODES = {
    BIC.OST_Walls: "WA",
    BIC.OST_Floors: "FL",
    BIC.OST_GenericModel: "GM",
    BIC.OST_StructuralFraming: "SF",
    BIC.OST_StructuralFoundation: "SFO",
    BIC.OST_StructuralColumns: "SC",
}
 
cfg = CONFIG
 
# --------------------------------------------------------------------------
def _find_context():
    try:
        import builtins as _b
    except ImportError:
        import __builtin__ as _b
    pools = [globals(), vars(_b)]
 
    def lookup(name):
        for pool in pools:
            if name in pool:
                return pool[name]
        return None
 
    uidoc = lookup("uidoc") or lookup("__uidoc__")
    if uidoc is None:
        app = lookup("__revit__") or lookup("uiapp")
        if app is not None and hasattr(app, "ActiveUIDocument"):
            uidoc = app.ActiveUIDocument
    if uidoc is not None:
        return uidoc, uidoc.Document
 
    d = lookup("doc") or lookup("__doc__revit")
    if isinstance(d, DB.Document):
        return None, d
 
    raise Exception("Geen actief Revit-document gevonden.\n"
                    "Verwacht een variabele '__revit__', 'uiapp', 'uidoc' of 'doc' "
                    "die door de plug-in wordt meegegeven.")
 
 
uidoc, doc = _find_context()
# --------------------------------------------------------------------------
def alert(msg, details=None):
    td = TaskDialog(TITLE)
    td.MainContent = msg
    if details:
        td.ExpandedContent = details
    td.Show()
 
 
def ask_yes_no(msg, yes_text="Ja, doorgaan", no_text="Nee, stoppen", details=None):
    td = TaskDialog(TITLE)
    td.MainContent = msg
    if details:
        td.ExpandedContent = details
    td.AddCommandLink(TaskDialogCommandLinkId.CommandLink1, yes_text)
    td.AddCommandLink(TaskDialogCommandLinkId.CommandLink2, no_text)
    return td.Show() == TaskDialogResult.CommandLink1
 
 
def select_elements(elements):
    if uidoc is None or not elements:
        return
    ids = List[DB.ElementId]()
    for e in elements:
        ids.Add(e.Id)
    uidoc.Selection.SetElementIds(ids)
# --------------------------------------------------------------------------
def id_value(eid):
    """ElementId -> int (Revit 2024+ .Value, oudere versies .IntegerValue)."""
    return eid.Value if hasattr(eid, "Value") else eid.IntegerValue
 
 
CODE_BY_CAT_ID = dict((id_value(DB.ElementId(bic)), code)
                      for bic, code in CATEGORY_CODES.items())
 
 
def get_name(element):
    if element is None:
        return ""
    try:
        return element.Name or ""
    except Exception:
        p = element.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME)
        return (p.AsString() or "") if p is not None else ""
 
 
def get_type(element):
    tid = element.GetTypeId()
    if tid == DB.ElementId.InvalidElementId:
        return None
    return element.Document.GetElement(tid)
 
 
def get_param(element, name):
    """Instance eerst, daarna type. 'Mark' -> ingebouwde Mark-parameter."""
    if name == "Mark":
        p = element.get_Parameter(DB.BuiltInParameter.ALL_MODEL_MARK)
        if p is not None:
            return p
    p = element.LookupParameter(name)
    if p is not None:
        return p
    t = get_type(element)
    return t.LookupParameter(name) if t is not None else None
 
 
def param_to_string(param):
    if param is None or not param.HasValue:
        return None
    st = param.StorageType
    if st == DB.StorageType.String:
        val = param.AsString()
    elif st == DB.StorageType.ElementId:
        eid = param.AsElementId()
        el = doc.GetElement(eid) if eid != DB.ElementId.InvalidElementId else None
        val = el.Name if el is not None else None
    else:
        val = param.AsValueString()
    if val is None:
        return None
    val = val.strip()
    return val if val else None
 
 
def get_value(element, name):
    return param_to_string(get_param(element, name))
 
 
def family_and_type_name(element):
    t = get_type(element)
    if t is None:
        return ""
    fam = t.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
    fam_name = (fam.AsString() or "") if fam is not None and fam.HasValue else ""
    return fam_name + " " + get_name(t)
 
 
LENGTH_UNIT = doc.GetUnits().GetFormatOptions(DB.SpecTypeId.Length).GetUnitTypeId()
 
 
def to_display(feet):
    return DB.UnitUtils.ConvertFromInternalUnits(feet, LENGTH_UNIT)
 
 
def set_param(element, name, text, internal_value=None):
    p = get_param(element, name)
    if p is None:
        return "parameter '{}' ontbreekt".format(name)
    if p.IsReadOnly:
        return "parameter '{}' is read-only".format(name)
    st = p.StorageType
    try:
        if st == DB.StorageType.String:
            p.Set(text)
        elif st == DB.StorageType.Double and internal_value is not None:
            p.Set(float(internal_value))
        elif st == DB.StorageType.Integer and internal_value is not None:
            p.Set(int(round(internal_value)))
        else:
            return "parameter '{}' heeft een onverwacht type".format(name)
    except Exception as ex:
        return "parameter '{}': {}".format(name, ex)
    return None
# --------------------------------------------------------------------------
GEOM_OPTIONS = DB.Options()
GEOM_OPTIONS.DetailLevel = DB.ViewDetailLevel.Fine
GEOM_OPTIONS.ComputeReferences = False
 
 
def collect_solids(geom, result):
    for obj in geom:
        if isinstance(obj, DB.Solid):
            if obj.Volume > 0:
                result.append(obj)
        elif isinstance(obj, DB.GeometryInstance):
            collect_solids(obj.GetInstanceGeometry(), result)
 
 
def get_solids(element):
    solids = []
    geom = element.get_Geometry(GEOM_OPTIONS)
    if geom is not None:
        collect_solids(geom, solids)
    return solids
 
 
def transform_bbox(bb, transform):
    pts = [DB.XYZ(x, y, z)
           for x in (bb.Min.X, bb.Max.X)
           for y in (bb.Min.Y, bb.Max.Y)
           for z in (bb.Min.Z, bb.Max.Z)]
    tp = [transform.OfPoint(p) for p in pts]
    return (DB.XYZ(min(p.X for p in tp), min(p.Y for p in tp), min(p.Z for p in tp)),
            DB.XYZ(max(p.X for p in tp), max(p.Y for p in tp), max(p.Z for p in tp)))
 
 
def max_overlap(solids_a, solids_b):
    best = 0.0
    for a in solids_a:
        for b in solids_b:
            try:
                inter = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                    a, b, DB.BooleanOperationsType.Intersect)
                if inter is not None and inter.Volume > best:
                    best = inter.Volume
            except Exception:
                pass
    return best
# --------------------------------------------------------------------------
def to_category_list(bics):
    lst = List[BIC]()
    for b in bics:
        lst.Add(b)
    return lst
 
 
def link_file_name(link_inst):
    link_doc = link_inst.GetLinkDocument()
    if link_doc is not None and link_doc.PathName:
        return os.path.splitext(os.path.basename(link_doc.PathName))[0]
    name = get_name(link_inst).split(" :")[0]
    return os.path.splitext(name)[0]
 
 
def workset_name(element):
    d = element.Document
    if not d.IsWorkshared:
        return ""
    ws = d.GetWorksetTable().GetWorkset(element.WorksetId)
    return ws.Name if ws is not None else ""
 
 
def passes_rule(element, rule):
    if rule["exclude_type_name_contains"]:
        tname = get_name(get_type(element))
        if any(t in tname for t in rule["exclude_type_name_contains"]):
            return False
    if rule["exclude_workset_contains"]:
        wname = workset_name(element)
        if any(w in wname for w in rule["exclude_workset_contains"]):
            return False
    return True
 
# ---------- Linkkeuze: geheugen per project ----------
def project_key():
    """Unieke sleutel per project (centraal model indien workshared)."""
    try:
        if doc.IsWorkshared:
            mp = doc.GetWorksharingCentralModelPath()
            if mp is not None:
                return DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(mp)
    except Exception:
        pass
    return doc.PathName or doc.Title
 
 
def load_memory():
    try:
        with io.open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get(project_key())
    except Exception:
        return None
 
 
def save_memory(choice):
    try:
        data = {}
        if os.path.exists(MEMORY_FILE):
            with io.open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        data[project_key()] = choice
        folder = os.path.dirname(MEMORY_FILE)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with io.open(MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write(u"{}".format(json.dumps(data, indent=2)))
    except Exception:
        pass  # geheugen is een extraatje, nooit een reden om te stoppen
     
# ---------- Linkkeuze: dialoog ----------
def pick_links():
    """Laat de gebruiker per rol links kiezen.
    Geeft [(linkinstance, regel), ...] terug, of None bij Annuleren."""
    loaded, unloaded = [], 0
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        if li.GetLinkDocument() is None:
            unloaded += 1
        else:
            loaded.append(li)
    if not loaded:
        return []
    loaded.sort(key=lambda li: link_file_name(li).lower())
 
    # Label per link; bij meerdere instances van dezelfde link het ID erbij
    names = [link_file_name(li) for li in loaded]
    labels = []
    for li, n in zip(loaded, names):
        labels.append(n if names.count(n) == 1
                      else u"{}  (instance {})".format(n, id_value(li.Id)))
 
    memory = load_memory()  # {"STRUCTURE": [labels], ...} of None
 
    form = WF.Form()
    form.Text = TITLE + " - gelinkte modellen"
    form.StartPosition = WF.FormStartPosition.CenterScreen
    form.AutoScaleMode = WF.AutoScaleMode.Dpi
    form.Size = SD.Size(560, 520)
    form.MinimumSize = SD.Size(420, 380)
    form.MinimizeBox = False
    form.MaximizeBox = False
    form.ShowInTaskbar = False
    form.TopMost = True
 
    layout = WF.TableLayoutPanel()
    layout.Dock = WF.DockStyle.Fill
    layout.Padding = WF.Padding(10)
    layout.ColumnCount = 1
 
    def add_row(ctrl, size_type, value=0):
        layout.RowStyles.Add(WF.RowStyle(size_type, value))
        layout.Controls.Add(ctrl, 0, layout.RowStyles.Count - 1)
 
    info = WF.Label()
    info.AutoSize = True
    info.Text = ("Vink per rol het gelinkte model aan waarin de hosts gezocht worden."
                 + ("\n({} niet-geladen link(s) worden niet getoond.)".format(unloaded)
                    if unloaded else ""))
    add_row(info, WF.SizeType.AutoSize)
 
    boxes = []
    for rule in ROLE_RULES:
        lbl = WF.Label()
        lbl.AutoSize = True
        lbl.Font = SD.Font(lbl.Font, SD.FontStyle.Bold)
        lbl.Margin = WF.Padding(0, 10, 0, 2)
        lbl.Text = rule["label"]
        add_row(lbl, WF.SizeType.AutoSize)
 
        clb = WF.CheckedListBox()
        clb.Dock = WF.DockStyle.Fill
        clb.CheckOnClick = True
        clb.IntegralHeight = False
        remembered = memory.get(rule["role"]) if memory else None
        for i, label in enumerate(labels):
            clb.Items.Add(label)
            if remembered is not None:
                checked = label in remembered
            else:
                up = names[i].upper()
                checked = any(h.upper() in up for h in rule["hint"])
            clb.SetItemChecked(i, checked)
        add_row(clb, WF.SizeType.Percent, 50)
        boxes.append((rule, clb))
 
    buttons = WF.FlowLayoutPanel()
    buttons.FlowDirection = WF.FlowDirection.RightToLeft
    buttons.Dock = WF.DockStyle.Fill
    buttons.AutoSize = True
    buttons.Margin = WF.Padding(0, 10, 0, 0)
    btn_cancel = WF.Button()
    btn_cancel.Text = "Annuleren"
    btn_cancel.DialogResult = WF.DialogResult.Cancel
    btn_ok = WF.Button()
    btn_ok.Text = "OK"
    btn_ok.DialogResult = WF.DialogResult.OK
    buttons.Controls.Add(btn_cancel)
    buttons.Controls.Add(btn_ok)
    add_row(buttons, WF.SizeType.AutoSize)
 
    form.Controls.Add(layout)
    form.AcceptButton = btn_ok
    form.CancelButton = btn_cancel
 
    if form.ShowDialog() != WF.DialogResult.OK:
        return None
 
    result, choice = [], {}
    for rule, clb in boxes:
        choice[rule["role"]] = []
        for i in range(clb.Items.Count):
            if clb.GetItemChecked(i):
                result.append((loaded[i], rule))
                choice[rule["role"]].append(labels[i])
    save_memory(choice)
    form.Dispose()
    return result
 
 
def find_best_host(opening_solids, opening_bb, links):
    best = None  # (volume, element, linkinstance)
    for li, rule in links:
        link_doc = li.GetLinkDocument()
        transform = li.GetTotalTransform()
        mn, mx = transform_bbox(opening_bb, transform.Inverse)
        bb_filter = DB.BoundingBoxIntersectsFilter(DB.Outline(mn, mx))
        cat_filter = DB.ElementMulticategoryFilter(to_category_list(rule["categories"]))
        candidates = (DB.FilteredElementCollector(link_doc)
                      .WherePasses(cat_filter)
                      .WherePasses(bb_filter)
                      .WhereElementIsNotElementType())
        for el in candidates:
            if not passes_rule(el, rule):
                continue
            link_solids = []
            for s in get_solids(el):
                try:
                    link_solids.append(DB.SolidUtils.CreateTransformed(s, transform))
                except Exception:
                    pass
            vol = max_overlap(opening_solids, link_solids)
            if vol > cfg["min_intersection_volume"] and (best is None or vol > best[0]):
                best = (vol, el, li)
    return best

# --------------------------------------------------------------------------
def get_level(element):
    lid = element.LevelId
    if lid == DB.ElementId.InvalidElementId:
        for bip in (DB.BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM,
                    DB.BuiltInParameter.FAMILY_LEVEL_PARAM,
                    DB.BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM):
            p = element.get_Parameter(bip)
            if p is not None and p.AsElementId() != DB.ElementId.InvalidElementId:
                lid = p.AsElementId()
                break
    lvl = doc.GetElement(lid) if lid != DB.ElementId.InvalidElementId else None
    return lvl if isinstance(lvl, DB.Level) else None
 
 
def get_height(element):
    p = get_param(element, cfg["param_height"])
    if p is None or not p.HasValue or p.StorageType != DB.StorageType.Double:
        return 0.0
    return p.AsDouble()
 
 
def extract_number(mark, sep, position):
    if not mark:
        return 0
    parts = mark.split(sep)
    if len(parts) <= position:
        return 0
    try:
        return int(float(parts[position].strip()))
    except ValueError:
        return 0
 
 
def format_number(number, padding):
    return str(number).zfill(padding) if padding > 0 else str(number)
# --------------------------------------------------------------------------
def write_report(openings, host_plan, number_plan, skipped, errors):
    by_id = {}
    for e in openings:
        by_id[id_value(e.Id)] = {"id": str(id_value(e.Id)), "fouten": []}
    for p in host_plan:
        r = by_id[id_value(p["el"].Id)]
        h = p["host"] or {}
        r["cat"] = h.get("category", "")
        r["host_el"] = h.get("element", "")
        r["link"] = h.get("link", "")
        r["host_id"] = h.get("id", "")
        r["z_param"] = (p["z_param"] or "").replace("DBU_CTE_", "")
        r["z"] = str(int(round(to_display(p["z_ft"])))) if p["z_param"] else ""
    for e, old, new in number_plan:
        r = by_id[id_value(e.Id)]
        r["oud"], r["nieuw"] = old, new
    for e in skipped:
        by_id[id_value(e.Id)]["fouten"].append("niet genummerd: lege parameters")
    for e, err in errors:
        by_id[id_value(e.Id)]["fouten"].append(err)
 
    cols = [("id", "Element ID"), ("cat", "Host Cat."), ("host_el", "Host element"),
            ("link", "Link"), ("host_id", "Host ID"), ("z_param", "Z-param"),
            ("z", "Z"), ("oud", "Oude Mark"), ("nieuw", "Nieuwe Mark")]
    path = os.path.join(tempfile.gettempdir(), "Openings_rapport.csv")
    with io.open(path, "w", encoding="utf-8-sig") as f:
        f.write(u";".join([c[1] for c in cols] + [u"Opmerking"]) + u"\n")
        for key in sorted(by_id):
            r = by_id[key]
            vals = [u"{}".format(r.get(c[0], "")).replace(";", ",") for c in cols]
            vals.append(u" | ".join(r["fouten"]).replace(";", ","))
            f.write(u";".join(vals) + u"\n")
    return path
# ==========================================================================
def main():
    if not (cfg["run_host_params"] or cfg["run_numbering"]):
        alert("Beide stappen staan uit in CONFIG.")
        return
 
    # ---------------- 0. Sparingen ophalen ----------------
    openings = [e for e in DB.FilteredElementCollector(doc)
                .OfCategory(cfg["opening_category"])
                .WhereElementIsNotElementType()
                if cfg["opening_family_filter"] in family_and_type_name(e)]
    openings.sort(key=lambda e: id_value(e.Id))
 
    if not openings:
        alert("Geen sparingen gevonden met '{}' in familie- of typenaam."
              .format(cfg["opening_family_filter"]))
        return
 
    needed = []
    if cfg["run_host_params"]:
        needed += [cfg[k] for k in ("param_host_category", "param_host_element",
                                    "param_host_link", "param_host_id",
                                    "param_z_top", "param_z_center")]
    if cfg["run_numbering"]:
        needed += [cfg[k] for k in ("param_discipline", "param_level",
                                    "param_host_category")]
    seen = set()
    needed = [n for n in needed if not (n in seen or seen.add(n))]
    missing = [n for n in needed if get_param(openings[0], n) is None]
    if missing:
        alert("Deze parameters ontbreken op de sparingen:\n- {}"
              .format("\n- ".join(missing)))
        return
 
    # ---------------- 1. Analyse host + Z ----------------
    host_plan = []
    host_cat_after = {}
    if cfg["run_host_params"]:
        links = pick_links()
        if links is None:  # Annuleren
            return
        if not links:
            if not ask_yes_no(
                    "Geen (geladen) gelinkt model geselecteerd.\n\n"
                    "Verder zonder host-detectie (alleen Z-waarden{})?"
                    .format(" en nummering" if cfg["run_numbering"] else "")):
                return
 
        for op in openings:
            item = {"el": op, "host": None, "z_param": None, "z_ft": None}
 
            bb = op.get_BoundingBox(None)
            solids = get_solids(op)
            if links and bb is not None and solids:
                best = find_best_host(solids, bb, links)
                if best is not None:
                    _, host_el, li = best
                    cat = host_el.Category
                    code = CODE_BY_CAT_ID.get(id_value(cat.Id), cat.Name) if cat else ""
                    item["host"] = {
                        "category": code,
                        "element": get_name(host_el),
                        "link": link_file_name(li),
                        "id": str(id_value(host_el.Id)),
                    }
 
            loc = op.Location
            lvl = get_level(op)
            if isinstance(loc, DB.LocationPoint) and lvl is not None:
                z = loc.Point.Z - lvl.ProjectElevation
                if cfg["rectangular_filter"] in family_and_type_name(op):
                    item["z_param"] = cfg["param_z_top"]
                    item["z_ft"] = z + get_height(op) / 2.0
                else:
                    item["z_param"] = cfg["param_z_center"]
                    item["z_ft"] = z
 
            if item["host"]:
                host_cat_after[id_value(op.Id)] = item["host"]["category"]
            elif cfg["clear_when_no_host"]:
                host_cat_after[id_value(op.Id)] = ""
            host_plan.append(item)
 
    with_host = [p for p in host_plan if p["host"]]
    without_host = [p for p in host_plan if not p["host"]]
    without_z = [p for p in host_plan if p["z_param"] is None]
 
    # ---------------- 2. Analyse nummering ----------------
    def host_category(e):
        key = id_value(e.Id)
        if key in host_cat_after:
            val = host_cat_after[key]
            return (val.strip() or None) if val else None
        return get_value(e, cfg["param_host_category"])
 
    number_plan, numbered, skipped = [], [], []
    if cfg["run_numbering"]:
        sep = cfg["separator"]
        regex = re.compile(cfg["numbered_regex"])
        to_number = []
        for e in openings:
            mark = get_value(e, cfg["param_mark"])
            (numbered if mark and regex.match(mark) else to_number).append(e)
 
        def group_key(e):
            return (get_value(e, cfg["param_level"]) or "",
                    get_value(e, cfg["param_discipline"]) or "")
 
        max_per_group = {}
        for e in numbered:
            key = group_key(e)
            nr = extract_number(get_value(e, cfg["param_mark"]), sep, cfg["number_position"])
            max_per_group[key] = max(max_per_group.get(key, 0), nr)
 
        groups, group_order = {}, []
        for e in to_number:
            disc = get_value(e, cfg["param_discipline"])
            lvl = get_value(e, cfg["param_level"])
            host = host_category(e)
            if not (disc and lvl and host):
                skipped.append(e)
                continue
            key = (lvl, disc)
            if key not in groups:
                groups[key] = []
                group_order.append(key)
            groups[key].append((e, disc, lvl, host))
 
        for key in group_order:
            counter = max_per_group.get(key, 0)
            for e, disc, lvl, host in groups[key]:
                counter += 1
                new_mark = sep.join([disc, lvl, host,
                                     format_number(counter, cfg["number_padding"])])
                number_plan.append((e, get_value(e, cfg["param_mark"]) or "", new_mark))
 
    if not host_plan and not number_plan:
        alert("Niets te doen: alle {} sparingen zijn al genummerd of missen "
              "Discipline, Niveau of Host Category.".format(len(openings)))
        return
 
    # ---------------- Bevestigen ----------------
    lines = ["{} sparingen gevonden.".format(len(openings))]
    if cfg["run_host_params"]:
        lines += ["", "STAP 1 - Host en Z-waarden",
                  "  Host gevonden: {}".format(len(with_host)),
                  "  Geen host: {}".format(len(without_host)),
                  "  Geen Z-waarde: {}".format(len(without_z))]
    if cfg["run_numbering"]:
        lines += ["", "STAP 2 - Nummering",
                  "  Al genummerd: {}".format(len(numbered)),
                  "  Worden genummerd: {}".format(len(number_plan)),
                  "  Overgeslagen (lege parameters): {}".format(len(skipped))]
    summary = "\n".join(lines)
    if cfg["ask_confirmation"] and not ask_yes_no(summary + "\n\nParameters wegschrijven?"):
        return
 
    # ---------------- Wegschrijven: 1 transactie ----------------
    errors = []
    t = DB.Transaction(doc, "Openings: host-parameters + nummering")
    t.Start()
    try:
        for p in host_plan:
            el, h = p["el"], p["host"]
            if h:
                for key, val in (("param_host_category", h["category"]),
                                 ("param_host_element", h["element"]),
                                 ("param_host_link", h["link"]),
                                 ("param_host_id", h["id"])):
                    err = set_param(el, cfg[key], val)
                    if err:
                        errors.append((el, err))
            elif cfg["clear_when_no_host"]:
                for key in ("param_host_category", "param_host_element",
                            "param_host_link", "param_host_id"):
                    set_param(el, cfg[key], "")
            if p["z_param"]:
                text = str(int(round(to_display(p["z_ft"]))))
                err = set_param(el, p["z_param"], text, p["z_ft"])
                if err:
                    errors.append((el, err))
 
        for e, old, new in number_plan:
            prm = get_param(e, cfg["param_mark"])
            if prm is None or prm.IsReadOnly:
                errors.append((e, "Mark is read-only"))
                continue
            try:
                prm.Set(new)
            except Exception as ex:
                errors.append((e, "Mark: {}".format(ex)))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
 
    # ---------------- Rapport ----------------
    report = write_report(openings, host_plan, number_plan, skipped, errors)
    problems = [e for e, _ in errors] + skipped
 
    td = TaskDialog(TITLE)
    td.MainInstruction = "Klaar - {} fout(en), {} overgeslagen".format(
        len(errors), len(skipped))
    td.MainContent = summary
    if errors:
        td.ExpandedContent = "\n".join("{}  {}".format(id_value(e.Id), err)
                                       for e, err in errors[:30])
    td.AddCommandLink(TaskDialogCommandLinkId.CommandLink1, "Rapport openen (CSV)")
    if problems and uidoc is not None:
        td.AddCommandLink(TaskDialogCommandLinkId.CommandLink2,
                          "Overgeslagen en mislukte sparingen selecteren")
    td.AddCommandLink(TaskDialogCommandLinkId.CommandLink3, "Sluiten")
    res = td.Show()
    if res == TaskDialogResult.CommandLink1:
        os.startfile(report)
    elif res == TaskDialogResult.CommandLink2:
        select_elements(problems)
 
 
main()
 
