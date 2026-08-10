"""Configurações de sites para o módulo Scraping Resilience.

Cada site concorrente que requer cookies de geolocalização ou
configurações especiais de navegação tem seu módulo aqui.

Configurações são armazenadas como dicts Python (não hardcoded no código
de execução) para permitir atualização sem alterar lógica de negócio.
"""

from scraping_resilience.site_configs.giga_fibra import GIGA_FIBRA_CONFIG

__all__ = ["GIGA_FIBRA_CONFIG"]
