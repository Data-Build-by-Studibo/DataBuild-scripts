# -*- coding: utf-8 -*-

import os
import re

from System.Collections.Generic import List
from pyrevit import revit, DB, forms, script

BIC = DB.BuiltInCategory

# --------------------------------------------------------------------------
# CONFIG - pas hier aan per bureaustandaard, niet per project
# --------------------------------------------------------------------------
CONFIG = {
    # Welke stappen uitvoeren
    "run_host_params": True,
    "run_numbering": True,

    # Sparingen in het actieve model
    "opening_category": BIC.OST_GenericModel,
    "opening_family_filter": "DBU_Opening",

    # ---- Gedeeld: stap 1 schrijft, stap 2 leest ----
    "param_host_category": "DBU_CTE_Opening Host Category",

    # ---- Stap 1: host- en Z-parameters ----
    "param_host_element": "DBU_CTE_Opening Host Element",
    "param_host_link": "DBU_CTE_Opening Host Link",
    "param_host_id": "DBU_CTE_Host ID",
    "param_z_top": "DBU_CTE_Z Value - Top",
    "param_z_center": "DBU_CTE_Z Value - Center",
    # Rechthoekig of niet: tekst in familie- of typenaam
    "rectangular_filter": "Rectangular",
    # Hoogteparameter van rechthoekige sparingen (instance of type)
    "param_height": "Element Height",
    # Minimale overlap (ft3) om als clash te tellen
    "min_intersection_volume": 1e-4,
    # Host-parameters leegmaken als er geen host meer gevonden wordt
    "clear_when_no_host": False,

    # ---- Stap 2: nummering ----
    "param_discipline": "DBU_CTE_Discipline",
    "param_level": "DBU_CTE_Niveau",
    "param_mark": "Mark",  # wordt omgezet naar de ingebouwde Mark-parameter
    "separator": "-",
    # Patroon van een reeds genummerde Mark
    "numbered_regex": r"^[A-Za-z]+-.+-[A-Za-z]+-.+$",
    # Positie van het nummer in de Mark (0-gebaseerd): D-N-H-[3]
    "number_position": 3,
    # Aantal cijfers (0 = geen voorloopnullen, 3 = 001, 002, ...)
    "number_padding": 0,

    # Eerst samenvatting tonen en om bevestiging vragen
    "ask_confirmation": True,
}

# Welke links en welke elementen daarin als host gelden.
LINK_RULES = [
    {
        "link_name_contains": "STRUCTURE",
        "categories": [BIC.OST_Walls, BIC.OST_StructuralFraming,
                       BIC.OST_StructuralColumns, BIC.OST_StructuralFoundation,
                       BIC.OST_Floors],
        "exclude_type_name_contains": ["Secant"],
        "exclude_workset_contains": [],
    },
    {
        "link_name_contains": "ARCHITECTURE",
        "categories": [BIC.OST_Walls, BIC.OST_StructuralFraming,
                       BIC.OST_StructuralColumns, BIC.OST_GenericModel],
        "exclude_type_name_contains": [],
        "exclude_workset_contains": [u"Stabilité"],
    },
]

# Afkortingen voor Host Category (onbekende categorie -> categorienaam)
CATEGORY_CODES = {
    BIC.OST_Walls: "WA",
    BIC.OST_Floors: "FL",
    BIC.OST_GenericModel: "GM",
    BIC.OST_StructuralFraming: "SF",
    BIC.OST_StructuralFoundation: "SFO",
    BIC.OST_StructuralColumns: "SC",
}

doc = revit.doc
output = script.get_output()
cfg = CONFIG


# --------------------------------------------------------------------------
# Algemene hulpfuncties
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
    """Waarde van een parameter als tekst (of None)."""
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
    """Tekstparameter krijgt 'text', lengte/getal krijgt 'internal_value'.
    Geeft foutmelding of None."""
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
# Geometrie
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
# Links
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


def matching_links():
    """(linkinstance, regel) voor geladen links die matchen."""
    result = []
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        if li.GetLinkDocument() is None:
            continue
        name = get_name(li)
        for rule in LINK_RULES:
            if rule["link_name_contains"] in name:
                result.append((li, rule))
    return result


def find_best_host(opening_solids, opening_bb, links):
    """Gelinkt element met de grootste overlap: (volume, element, linkinstance)."""
    best = None
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
# Niveau en Z-waarde
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


# --------------------------------------------------------------------------
# Nummering
# --------------------------------------------------------------------------
def extract_number(mark, sep, position):
    """Nummer uit de Mark; 0 als dat niet lukt."""
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


# ==========================================================================
# 0. Sparingen ophalen en parameters controleren
# ==========================================================================
if not (cfg["run_host_params"] or cfg["run_numbering"]):
    forms.alert("Beide stappen staan uit in CONFIG.", exitscript=True)

openings = [e for e in DB.FilteredElementCollector(doc)
            .OfCategory(cfg["opening_category"])
            .WhereElementIsNotElementType()
            if cfg["opening_family_filter"] in family_and_type_name(e)]
openings.sort(key=lambda e: id_value(e.Id))

if not openings:
    forms.alert("Geen sparingen gevonden met '{}' in familie- of typenaam."
                .format(cfg["opening_family_filter"]), exitscript=True)

needed = []
if cfg["run_host_params"]:
    needed += [cfg[k] for k in ("param_host_category", "param_host_element",
                                "param_host_link", "param_host_id",
                                "param_z_top", "param_z_center")]
if cfg["run_numbering"]:
    needed += [cfg[k] for k in ("param_discipline", "param_level",
                                "param_host_category")]
needed = list(dict.fromkeys(needed))  # dubbels weg, volgorde behouden
missing = [n for n in needed if get_param(openings[0], n) is None]
if missing:
    forms.alert("Deze parameters ontbreken op de sparingen:\n- {}"
                .format("\n- ".join(missing)), exitscript=True)


# ==========================================================================
# 1. Analyse host + Z (nog niets wegschrijven)
# ==========================================================================
host_plan = []       # dict per sparing
host_cat_after = {}  # element-id -> Host Category zoals die na stap 1 zal zijn

if cfg["run_host_params"]:
    links = matching_links()
    if not links:
        if not forms.alert("Geen geladen links gevonden die matchen met:\n- {}\n\n"
                           "Verder zonder host-detectie (alleen Z-waarden{})?"
                           .format("\n- ".join(r["link_name_contains"] for r in LINK_RULES),
                                   " en nummering" if cfg["run_numbering"] else ""),
                           yes=True, no=True):
            script.exit()

    with forms.ProgressBar(title="Sparingen analyseren ({value}/{max_value})") as pb:
        for i, op in enumerate(openings):
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

            # Wat stap 2 straks als Host Category moet zien
            if item["host"]:
                host_cat_after[id_value(op.Id)] = item["host"]["category"]
            elif cfg["clear_when_no_host"]:
                host_cat_after[id_value(op.Id)] = ""

            host_plan.append(item)
            pb.update_progress(i + 1, len(openings))

with_host = [p for p in host_plan if p["host"]]
without_host = [p for p in host_plan if not p["host"]]
without_z = [p for p in host_plan if p["z_param"] is None]


# ==========================================================================
# 2. Analyse nummering (gebruikt de Host Category uit stap 1)
# ==========================================================================
def host_category(e):
    key = id_value(e.Id)
    if key in host_cat_after:
        val = host_cat_after[key]
        return (val.strip() or None) if val else None
    return get_value(e, cfg["param_host_category"])


number_plan = []  # (element, oude mark, nieuwe mark)
numbered = []
skipped = []

if cfg["run_numbering"]:
    sep = cfg["separator"]
    regex = re.compile(cfg["numbered_regex"])

    to_number = []
    for e in openings:
        mark = get_value(e, cfg["param_mark"])
        if mark and regex.match(mark):
            numbered.append(e)
        else:
            to_number.append(e)

    def group_key(e):
        return (get_value(e, cfg["param_level"]) or "",
                get_value(e, cfg["param_discipline"]) or "")

    max_per_group = {}
    for e in numbered:
        key = group_key(e)
        nr = extract_number(get_value(e, cfg["param_mark"]), sep, cfg["number_position"])
        max_per_group[key] = max(max_per_group.get(key, 0), nr)

    groups = {}
    group_order = []
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


# ==========================================================================
# Bevestigen (1 dialoog voor beide stappen)
# ==========================================================================
if not host_plan and not number_plan:
    forms.alert("Niets te doen: alle {} sparingen zijn al genummerd of missen "
                "Discipline, Niveau of Host Category.".format(len(openings)),
                exitscript=True)

if cfg["ask_confirmation"]:
    lines = ["{} sparingen gevonden.".format(len(openings))]
    if cfg["run_host_params"]:
        lines += ["",
                  "STAP 1 - Host en Z-waarden",
                  "  Host gevonden: {}".format(len(with_host)),
                  "  Geen host: {}".format(len(without_host)),
                  "  Geen Z-waarde (geen niveau of punt): {}".format(len(without_z))]
    if cfg["run_numbering"]:
        lines += ["",
                  "STAP 2 - Nummering",
                  "  Al genummerd: {}".format(len(numbered)),
                  "  Worden genummerd: {}".format(len(number_plan)),
                  "  Overgeslagen (lege parameters): {}".format(len(skipped))]
    lines += ["", "Doorgaan?"]
    if not forms.alert("\n".join(lines), yes=True, no=True):
        script.exit()


# ==========================================================================
# Wegschrijven - 1 transactie, dus 1x Ctrl+Z
# ==========================================================================
host_errors = []
number_errors = []
with revit.Transaction("Openings: host-parameters + nummering"):
    # Stap 1
    for p in host_plan:
        el = p["el"]
        h = p["host"]
        if h:
            for key, val in (("param_host_category", h["category"]),
                             ("param_host_element", h["element"]),
                             ("param_host_link", h["link"]),
                             ("param_host_id", h["id"])):
                err = set_param(el, cfg[key], val)
                if err:
                    host_errors.append((el, err))
        elif cfg["clear_when_no_host"]:
            for key in ("param_host_category", "param_host_element",
                        "param_host_link", "param_host_id"):
                set_param(el, cfg[key], "")

        if p["z_param"]:
            text = str(int(round(to_display(p["z_ft"]))))
            err = set_param(el, p["z_param"], text, p["z_ft"])
            if err:
                host_errors.append((el, err))

    # Stap 2
    for e, old, new in number_plan:
        p = get_param(e, cfg["param_mark"])
        try:
            if p is None or p.IsReadOnly:
                raise Exception("Mark is read-only")
            p.Set(new)
        except Exception as ex:
            number_errors.append((e, str(ex)))


# ==========================================================================
# Rapport
# ==========================================================================
if cfg["run_host_params"]:
    output.print_md("## Stap 1 - Host-parameters en Z-waarden")
    output.print_md("**{}** sparingen, **{}** met host, **{}** zonder host."
                    .format(len(host_plan), len(with_host), len(without_host)))
    rows = []
    for p in host_plan:
        h = p["host"] or {}
        z = str(int(round(to_display(p["z_ft"])))) if p["z_param"] else "-"
        rows.append([output.linkify(p["el"].Id),
                     h.get("category", "-"), h.get("element", "-"),
                     h.get("link", "-"), h.get("id", "-"),
                     (p["z_param"] or "-").replace("DBU_CTE_", ""), z])
    output.print_table(rows, columns=["Sparing", "Cat.", "Host element",
                                      "Link", "Host ID", "Z-param", "Z"])
    if host_errors:
        output.print_md("### Fouten stap 1")
        for el, err in host_errors:
            print("{}  {}".format(output.linkify(el.Id), err))

if cfg["run_numbering"]:
    failed_ids = set(id_value(f[0].Id) for f in number_errors)
    rows = [[output.linkify(e.Id), old, new]
            for e, old, new in number_plan if id_value(e.Id) not in failed_ids]
    output.print_md("## Stap 2 - Openings genummerd: {}".format(len(rows)))
    if rows:
        output.print_table(rows, columns=["Element", "Oude Mark", "Nieuwe Mark"])
    if skipped:
        output.print_md("### Overgeslagen (Discipline, Niveau of Host Category leeg)")
        for e in skipped:
            print(output.linkify(e.Id))
    if number_errors:
        output.print_md("### Fouten stap 2")
        for e, err in number_errors:
            print("{}  {}".format(output.linkify(e.Id), err))
