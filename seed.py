"""Dados de demonstração.

Cria duas empresas de propósito: com uma só, o isolamento entre tenants
nunca é realmente testado.

    python app.py seed-demo
"""
from db import execute, get_db, query
from security import ROLE_BUSINESS, hash_password
from services import now_iso, renew_subscription, unique_slug

DEMO = [
    {
        "nome": "Restaurante Kamba",
        "email": "kamba@exemplo.com",
        "whatsapp": "244923000001",
        "descricao": "Cozinha angolana com vista para a marginal.",
        "horario": "Seg a Sáb, 11h00 – 23h00",
        "morada": "Rua Rainha Ginga 120, Luanda",
        "categorias": {
            "Entradas": [
                ("Pastéis de bacalhau (4un)", "Massa estaladiça, bacalhau desfiado.", 250000),
                ("Sopa de peixe", "Peixe fresco do dia com legumes.", 180000),
            ],
            "Pratos principais": [
                ("Muamba de galinha", "Com funge, quiabo e óleo de palma.", 550000),
                ("Calulu de peixe seco", "Receita da casa, acompanha funge.", 600000),
                ("Hambúrguer especial", "Hambúrguer artesanal com queijo e bacon.", 500000),
            ],
            "Bebidas": [
                ("Refrigerante", "Lata 33cl.", 100000),
                ("Água mineral", "Garrafa 50cl.", 60000),
                ("Sumo natural de múcua", "Feito na hora.", 150000),
            ],
        },
        "pagamentos": [
            ("Multicaixa Express", "Número 923 000 001"),
            ("Dinheiro", "Pagamento na entrega ou no balcão"),
        ],
    },
    {
        "nome": "Café Luanda",
        "email": "cafe@exemplo.com",
        "whatsapp": "244923000002",
        "descricao": "Pequenos-almoços, pastelaria e café torrado no dia.",
        "horario": "Todos os dias, 06h30 – 20h00",
        "morada": "Largo do Kinaxixi, Luanda",
        "categorias": {
            "Pastelaria": [
                ("Croissant simples", "Manteiga, feito de manhã.", 80000),
                ("Pastel de nata", "Canela a pedido.", 70000),
            ],
            "Café": [
                ("Café expresso", "Torra média.", 50000),
                ("Galão", "Café com leite em copo alto.", 90000),
            ],
        },
        "pagamentos": [("Transferência bancária", "IBAN a pedido no balcão")],
    },
]


def seed_demo(app):
    with app.app_context():
        conn = get_db()
        plano = query(
            "SELECT * FROM plans WHERE status = 'active' ORDER BY price_cents", (), one=True
        )

        for d in DEMO:
            if query("SELECT id FROM users WHERE email = ?", (d["email"],), one=True):
                print(f"  {d['nome']}: já existe, ignorado.")
                continue

            slug = unique_slug(d["nome"])
            bid = execute(
                """INSERT INTO businesses (name, slug, description, whatsapp, address,
                        opening_hours, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'active', ?)""",
                (d["nome"], slug, d["descricao"], d["whatsapp"], d["morada"],
                 d["horario"], now_iso()),
            )
            execute(
                """INSERT INTO users (business_id, name, email, password_hash, role,
                                      status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?)""",
                (bid, f"Gestor {d['nome']}", d["email"], hash_password("demo12345"),
                 ROLE_BUSINESS, now_iso()),
            )
            if plano:
                renew_subscription(bid, plano["id"], plano["duration_days"])

            for pos, (cat_nome, produtos) in enumerate(d["categorias"].items()):
                cid = execute(
                    """INSERT INTO categories (business_id, name, position, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (bid, cat_nome, pos, now_iso()),
                )
                for i, (nome, desc, preco) in enumerate(produtos):
                    execute(
                        """INSERT INTO products (business_id, category_id, name,
                                description, price_cents, available, position,
                                created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                        (bid, cid, nome, desc, preco, i, now_iso(), now_iso()),
                    )

            for nome, detalhes in d["pagamentos"]:
                execute(
                    """INSERT INTO payment_methods (business_id, name, details, active)
                       VALUES (?, ?, ?, 1)""",
                    (bid, nome, detalhes),
                )

            print(f"  {d['nome']} → /menu/{slug}  (login: {d['email']} / demo12345)")

        conn.commit()
