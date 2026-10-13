"""
revit_mcp_server.py - Data Build MCP-server voor Claude Desktop.
Leest gegevens uit het actieve Revit-model via de Claude-bridge in de Data Build-plugin.
Alles is read-only.
"""
import httpx
from mcp.server.fastmcp import FastMCP

BRIDGE_URL = "http://localhost:48884/"
mcp = FastMCP("databuild-revit")


def _call(tool: str, **args):
    try:
        r = httpx.post(BRIDGE_URL, json={"tool": tool, "args": args}, timeout=70)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        return {"error": "Revit-bridge niet bereikbaar. Klik in Revit op Data Build > Claude zodat de knop 'Claude Aan' toont."}
    except httpx.TimeoutException:
        return {"error": "Revit antwoordt niet. Staat er een dialoogvenster open of is een commando bezig?"}


@mcp.tool()
def model_info() -> dict:
    """Algemene info over het actieve Revit-model: titel, pad, projectnaam/-nummer, niveaus,
    gelinkte modellen en aantal waarschuwingen. Gebruik dit als eerste stap."""
    return _call("model_info")


@mcp.tool()
def list_categories() -> list:
    """Alle modelcategorieën in het model met hun sleutel (bv. 'OST_Walls'),
    weergavenaam (bv. 'Muren') en aantal elementen. Gebruik dit om de juiste
    categorie-sleutel te vinden voor de andere tools."""
    return _call("list_categories")


@mcp.tool()
def get_elements(category: str, parameters: list[str] | None = None, limit: int = 200) -> dict:
    """Lijst elementen van één categorie met de gevraagde parameterwaarden
    (eerst instance-parameter, anders typeparameter).
    category: sleutel uit list_categories, bv. 'OST_Doors'.
    parameters: parameternamen exact zoals in Revit.
    limit: max. aantal elementen (standaard 200, max 2000)."""
    return _call("get_elements", category=category, parameters=parameters or [], limit=limit)


@mcp.tool()
def get_element(id: int) -> dict:
    """Alle instance- en typeparameters van één element op basis van zijn ElementId."""
    return _call("get_element", id=id)


@mcp.tool()
def check_parameters(category: str, parameters: list[str]) -> dict:
    """Controle: welke elementen van een categorie hebben een lege of ontbrekende waarde
    voor één of meer van de opgegeven parameters."""
    return _call("check_parameters", category=category, parameters=parameters)


@mcp.tool()
def get_warnings() -> dict:
    """Revit-waarschuwingen van het model, gegroepeerd per soort met aantallen
    en voorbeeld-ElementIds."""
    return _call("get_warnings")


@mcp.tool()
def get_selection() -> list:
    """De elementen die de gebruiker op dit moment in Revit geselecteerd heeft."""
    return _call("get_selection")


if __name__ == "__main__":
    mcp.run()