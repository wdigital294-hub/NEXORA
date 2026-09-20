"""Testes da NEXORA.

O foco não é cobertura de linhas: é atacar as promessas do sistema.
Se o isolamento entre empresas falhar, tudo o resto é irrelevante.

    python test_nexora.py
"""
import os
import re
import sys
import tempfile

os.environ["NEXORA_DB"] = os.path.join(tempfile.mkdtemp(), "teste.db")

from app import _init, create_app  # noqa: E402
from config import Config  # noqa: E402
from db import query  # noqa: E402
from seed import seed_demo  # noqa: E402

falhas = []


def verificar(descricao, condicao):
    marca = "ok  " if condicao else "FALHA"
    print(f"  [{marca}] {descricao}")
    if not condicao:
        falhas.append(descricao)


class Teste(Config):
    DATABASE_PATH = os.environ["NEXORA_DB"]
    UPLOAD_ROOT = os.path.join(tempfile.mkdtemp(), "uploads")
    TESTING = True
    SECRET_KEY = "teste"


def entrar(cliente, email, password="demo12345"):
    pagina = cliente.get("/login")
    token = re.search(rb'name="csrf_token" value="([^"]+)"', pagina.data).group(1).decode()
    return cliente.post(
        "/login", data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=True,
    )


def token_de(cliente, caminho):
    pagina = cliente.get(caminho)
    m = re.search(rb'name="csrf_token" value="([^"]+)"', pagina.data)
    return m.group(1).decode() if m else ""


def correr():
    app = create_app(Teste)
    _init(app)
    seed_demo(app)

    with app.app_context():
        kamba = query("SELECT * FROM businesses WHERE slug = 'restaurante-kamba'", (), one=True)
        cafe = query("SELECT * FROM businesses WHERE slug = 'cafe-luanda'", (), one=True)
        prod_kamba = query(
            "SELECT * FROM products WHERE business_id = ? LIMIT 1", (kamba["id"],), one=True
        )
        prod_cafe = query(
            "SELECT * FROM products WHERE business_id = ? LIMIT 1", (cafe["id"],), one=True
        )
        cat_cafe = query(
            "SELECT * FROM categories WHERE business_id = ? LIMIT 1", (cafe["id"],), one=True
        )

    print("\nIsolamento entre empresas (catálogo público)")
    with app.test_client() as c:
        pagina = c.get(f"/menu/{kamba['slug']}")
        html = pagina.data.decode()
        verificar("o catálogo do Kamba mostra produtos do Kamba",
                  prod_kamba["name"] in html)
        verificar("o catálogo do Kamba NÃO mostra produtos do Café Luanda",
                  prod_cafe["name"] not in html)
        verificar("slug inexistente devolve 404", c.get("/menu/nao-existe").status_code == 404)

    print("\nIntegridade de preços no pedido")
    with app.test_client() as c:
        r = c.post(f"/menu/{kamba['slug']}/pedido", json={
            "items": [{"id": prod_kamba["id"], "qty": 2}],
            "customer_name": "Cliente Teste",
        })
        dados = r.get_json()
        verificar("pedido válido é aceite", dados["ok"])
        esperado = prod_kamba["price_cents"] * 2
        with app.app_context():
            pedido = query("SELECT * FROM orders ORDER BY id DESC LIMIT 1", (), one=True)
        verificar("o total é calculado no servidor", pedido["total_cents"] == esperado)
        verificar("o link do WhatsApp aponta para o número do Kamba",
                  kamba["whatsapp"] in (dados["whatsapp_url"] or ""))

        # O ataque: o navegador tenta impor o seu próprio preço.
        r = c.post(f"/menu/{kamba['slug']}/pedido", json={
            "items": [{"id": prod_kamba["id"], "qty": 1, "price_cents": 1}],
        })
        with app.app_context():
            pedido = query("SELECT * FROM orders ORDER BY id DESC LIMIT 1", (), one=True)
        verificar("preço enviado pelo cliente é ignorado",
                  pedido["total_cents"] == prod_kamba["price_cents"])

        # O ataque: pedir no Kamba um produto do Café Luanda.
        r = c.post(f"/menu/{kamba['slug']}/pedido", json={
            "items": [{"id": prod_cafe["id"], "qty": 1}],
        })
        verificar("produto de outra empresa é rejeitado", r.status_code == 409)

        r = c.post(f"/menu/{kamba['slug']}/pedido", json={
            "items": [{"id": prod_kamba["id"], "qty": -5}],
        })
        verificar("quantidade negativa é rejeitada", r.status_code == 400)

    print("\nIsolamento entre painéis")
    with app.test_client() as c:
        entrar(c, "kamba@exemplo.com")
        verificar("o gestor entra no seu painel", c.get("/admin/").status_code == 200)

        # O ataque: editar por id um produto de outra empresa.
        r = c.get(f"/admin/produtos/{prod_cafe['id']}")
        verificar("abrir produto de outra empresa devolve 404", r.status_code == 404)

        tok = token_de(c, "/admin/produtos/novo")
        r = c.post(f"/admin/produtos/{prod_cafe['id']}", data={
            "name": "INVADIDO", "price": "1", "csrf_token": tok,
        })
        verificar("editar produto de outra empresa devolve 404", r.status_code == 404)
        with app.app_context():
            intacto = query(
                "SELECT * FROM products WHERE id = ?", (prod_cafe["id"],), one=True
            )
        verificar("o produto da outra empresa ficou intacto",
                  intacto["name"] == prod_cafe["name"])

        r = c.post(f"/admin/produtos/{prod_cafe['id']}/eliminar", data={"csrf_token": tok})
        verificar("eliminar produto de outra empresa devolve 404", r.status_code == 404)

        # O ataque: associar o meu produto a uma categoria de outra empresa.
        r = c.post("/admin/produtos/novo", data={
            "name": "Produto cruzado", "price": "1000",
            "category_id": cat_cafe["id"], "csrf_token": tok, "available": "on",
        }, follow_redirects=True)
        with app.app_context():
            novo = query(
                "SELECT * FROM products WHERE name = 'Produto cruzado'", (), one=True
            )
        verificar("categoria de outra empresa é descartada",
                  novo is not None and novo["category_id"] is None)

        verificar("empresa não entra no painel do proprietário",
                  c.get("/plataforma/").status_code == 403)

    print("\nAutorização e CSRF")
    with app.test_client() as c:
        verificar("painel da empresa exige sessão",
                  c.get("/admin/", follow_redirects=False).status_code == 302)
        verificar("painel do proprietário exige sessão",
                  c.get("/plataforma/", follow_redirects=False).status_code == 302)

    with app.test_client() as c:
        entrar(c, "kamba@exemplo.com")
        r = c.post("/admin/produtos/novo", data={"name": "Sem token", "price": "100"})
        verificar("POST sem token CSRF é recusado", r.status_code == 400)

    with app.test_client() as c:
        r = entrar(c, "kamba@exemplo.com", "password-errada")
        verificar("password errada não autentica", r.status_code == 401)

    print("\nProprietário da plataforma")
    with app.test_client() as c:
        entrar(c, "admin@nexora.com", "nexora12345")
        verificar("proprietário entra no seu painel", c.get("/plataforma/").status_code == 200)
        verificar("proprietário vê a lista de empresas",
                  b"Restaurante Kamba" in c.get("/plataforma/empresas").data)
        verificar("proprietário não entra no painel de empresa",
                  c.get("/admin/").status_code == 403)

    print("\nCiclo da assinatura")
    with app.app_context():
        from db import execute, get_db
        from services import subscription_state

        execute(
            "UPDATE subscriptions SET end_date = '2020-01-01' WHERE business_id = ?",
            (kamba["id"],),
        )
        get_db().commit()
        estado, _ = subscription_state(kamba["id"])
        verificar("assinatura vencida é detectada como expirada", estado == "expired")

    with app.test_client() as c:
        r = c.get(f"/menu/{kamba['slug']}")
        verificar("catálogo fecha com assinatura expirada", r.status_code == 503)
        r = c.post(f"/menu/{kamba['slug']}/pedido",
                   json={"items": [{"id": prod_kamba["id"], "qty": 1}]})
        verificar("pedidos são recusados com assinatura expirada", r.status_code == 403)

    with app.app_context():
        n = query(
            "SELECT COUNT(*) AS n FROM products WHERE business_id = ?", (kamba["id"],), one=True
        )["n"]
        verificar("os dados da empresa NÃO são apagados ao expirar", n > 0)

    with app.test_client() as c:
        entrar(c, "kamba@exemplo.com")
        r = c.get("/admin/produtos", follow_redirects=False)
        verificar("com assinatura expirada, a edição redirecciona para a assinatura",
                  r.status_code == 302 and "assinatura" in r.headers["Location"])
        verificar("a área de assinatura continua acessível",
                  c.get("/admin/assinatura").status_code == 200)

    with app.test_client() as c:
        r = c.get(f"/menu/{cafe['slug']}")
        verificar("o catálogo do Café Luanda não é afectado pelo Kamba",
                  r.status_code == 200)

    print("\nUtilitários")
    with app.app_context():
        from services import fmt_money, normalize_whatsapp, slugify, to_cents

        verificar("to_cents('5.000') = 500000 cêntimos", to_cents("5.000") == 500000)
        verificar("to_cents('1500,50') respeita cêntimos", to_cents("1500,50") == 150050)
        verificar("fmt_money formata milhares", fmt_money(1100000) == "11.000 Kz")
        verificar("slugify limpa acentos", slugify("Café Luanda!") == "cafe-luanda")
        verificar("whatsapp fica só com dígitos",
                  normalize_whatsapp("+244 923 000 001") == "244923000001")

    print()
    if falhas:
        print(f"{len(falhas)} teste(s) falharam:")
        for f in falhas:
            print("  -", f)
        return 1
    print("Todos os testes passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(correr())
