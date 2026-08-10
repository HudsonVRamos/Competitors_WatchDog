"""Configuração do site Giga+ Fibra para São Paulo.

Contém os 5 cookies interdependentes necessários para suprimir o popup
de seleção de cidade e carregar planos de São Paulo diretamente.

Valores descobertos via mapeamento completo do endpoint da API:
- PlanCity: ID numérico 329 (São Paulo)
- PlanName: "São Paulo" (URL-encoded para "S%C3%A3o%20Paulo")
- PlanRegion: "Território 02" (URL-encoded para "Territ%C3%B3rio%2002")
- PlanType: "PF" (Pessoa Física)
- redirectToWhatsapp: "false" (não redirecionar para WhatsApp)

Referência: gigamais_city_mapping_COMPLETO.json
"""

GIGA_FIBRA_CONFIG: dict = {
    "name": "Giga+ Fibra",
    "base_url": "https://www.gigamaisfibra.com.br",
    "modal_selector": (
        "[class*='modal'], .popup-localizacao, #popup-cidade"
    ),
    "geolocation_cookies": [
        {
            "name": "PlanCity",
            "value": "329",
            "domain": ".gigamaisfibra.com.br",
            "path": "/",
            "url_encode": False,
        },
        {
            "name": "PlanName",
            "value": "São Paulo",
            "domain": ".gigamaisfibra.com.br",
            "path": "/",
            "url_encode": True,
        },
        {
            "name": "PlanRegion",
            "value": "Território 02",
            "domain": ".gigamaisfibra.com.br",
            "path": "/",
            "url_encode": True,
        },
        {
            "name": "PlanType",
            "value": "PF",
            "domain": ".gigamaisfibra.com.br",
            "path": "/",
            "url_encode": False,
        },
        {
            "name": "redirectToWhatsapp",
            "value": "false",
            "domain": ".gigamaisfibra.com.br",
            "path": "/",
            "url_encode": False,
        },
    ],
}
