from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from app.services.ml_api_client import get_ml_client

router = APIRouter(prefix="/api/integrations/mercadolivre", tags=["Mercado Livre OAuth"])


@router.get("/status")
def ml_status():
    client = get_ml_client()
    return client.get_auth_status()


@router.get("/authorize")
def ml_authorize(redirect: bool = Query(default=False)):
    client = get_ml_client()

    try:
        authorization_url = client.get_authorization_url()
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    if redirect:
        return RedirectResponse(url=authorization_url, status_code=307)

    return {
        "authorization_url": authorization_url,
        "redirect_uri": client.auth.redirect_uri,
        "instructions": "Abra a URL no navegador, autorize o app e aguarde o callback nesta API.",
    }


@router.get("/callback", response_class=HTMLResponse)
async def ml_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    client = get_ml_client()

    if not client.auth.verify_state(state):
        raise HTTPException(status_code=400, detail="State inválido ou expirado")

    try:
        result = await client.auth.exchange_authorization_code(code)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    expires_in = result.get("expires_in", 0)
    return HTMLResponse(
        content=f"""
        <html>
          <head>
            <meta charset="utf-8" />
            <title>Mercado Livre conectado</title>
            <style>
              body {{
                font-family: Arial, sans-serif;
                background: #08111f;
                color: #e2e8f0;
                display: grid;
                place-items: center;
                min-height: 100vh;
                margin: 0;
              }}
              .card {{
                width: min(92vw, 640px);
                padding: 32px;
                border-radius: 20px;
                border: 1px solid rgba(148, 163, 184, 0.18);
                background: rgba(15, 23, 42, 0.92);
                box-shadow: 0 24px 60px rgba(2, 8, 23, 0.35);
              }}
              h1 {{
                margin: 0 0 12px;
                font-size: 28px;
              }}
              p {{
                margin: 0 0 10px;
                line-height: 1.5;
              }}
              code {{
                background: rgba(30, 41, 59, 0.9);
                border-radius: 10px;
                padding: 2px 8px;
              }}
            </style>
          </head>
          <body>
            <div class="card">
              <h1>Mercado Livre conectado com sucesso</h1>
              <p>O token OAuth foi salvo no backend e a integração já pode tentar a API oficial.</p>
              <p>Expiração do access token: <code>{expires_in}</code> segundos.</p>
              <p>Você já pode voltar para o sistema e repetir a consulta.</p>
            </div>
          </body>
        </html>
        """
    )
