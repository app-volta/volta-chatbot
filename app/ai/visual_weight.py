"""Fatores de teste da EPA, válidos apenas para as condições identificadas."""

from math import isfinite
from typing import Literal

from pydantic import Field

from app.db.models import AnaliseResiduoIA


class VisualWeightAnalysis(AnaliseResiduoIA):
    volume_liters: float | None = Field(default=None, gt=0, allow_inf_nan=False, description="Volume estimado ocupado em litros, apenas com referência visual suficiente.")
    volume_reference: str | None = Field(default=None, description="Referência visual para o volume; null se ausente.")
    density_case: Literal["flattened_cardboard", "loose_pet_hdpe_bottles", "food_waste"] | None = Field(default=None, description="Condição da tabela EPA que corresponde ao material; null se desconhecida.")


# EPA, Volume-to-Weight Conversion Factors (2016), pp. 3–4: libras por jarda cúbica.
EPA_FACTORS = {
    "flattened_cardboard": ("papelao", 106),
    "loose_pet_hdpe_bottles": ("plastico", 32),
    "food_waste": ("organico", 463),
}
EPA_SOURCE = "https://www.epa.gov/smm/volume-weight-conversion-factors-solid-waste"


def calculate_visual_weight(analysis: VisualWeightAnalysis) -> AnaliseResiduoIA:
    result = AnaliseResiduoIA.model_validate(analysis.model_dump(exclude={"volume_liters", "volume_reference", "density_case"}))
    case = EPA_FACTORS.get(analysis.density_case)
    if result.estimated_quantity_kg is not None or not case or analysis.waste_types != [case[0]] or analysis.volume_liters is None or not isfinite(analysis.volume_liters) or not (analysis.volume_reference or "").strip():
        return result
    kg = round(analysis.volume_liters / 1000 * case[1] * 0.45359237 / 0.764554857984, 2)
    return result.model_copy(update={
        "estimated_quantity_kg": kg,
        "report_text": f"{analysis.report_text}\nPeso aproximado: {kg} kg. Volume estimado: {analysis.volume_liters} L; referência visual: {analysis.volume_reference}. Fator EPA ({analysis.density_case}); sujeito a incerteza e confirmação por pesagem. Fonte: {EPA_SOURCE}",
    })
