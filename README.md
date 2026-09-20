# NEXORA

Uma única plataforma. Vários negócios.

Plataforma multiempresa de catálogos digitais: cada negócio tem o seu catálogo,
o seu QR Code, os seus produtos, os seus pedidos e o seu WhatsApp, tudo na mesma
instalação. A NEXORA cobra às empresas por assinatura.

## Arrancar

```bash
pip install -r requirements.txt
python app.py seed-demo     # cria a base + duas empresas de exemplo
python app.py               # http://127.0.0.1:5000
```

Para começar sem dados de exemplo, use `python app.py init-db` em vez de `seed-demo`.

**Contas criadas pelo `seed-demo`**

| Papel | Endereço | Email | Palavra-passe |
|---|---|---|---|
| Proprietário da NEXORA | `/plataforma` | admin@nexora.com | nexora12345 |
| Restaurante Kamba | `/admin` | kamba@exemplo.com | demo12345 |
| Café Luanda | `/admin` | cafe@exemplo.com | demo12345 |

Catálogos públicos: `/menu/restaurante-kamba` e `/menu/cafe-luanda`.

Mude a palavra-passe do proprietário antes de qualquer uso real. Em produção,
defina também `NEXORA_SECRET_KEY` e `NEXORA_HTTPS=1`.

## Verificar que está tudo de pé

```bash
python test_nexora.py
```

Percorre os fluxos principais e testa explicitamente o isolamento: uma empresa
não vê nem edita dados da outra, nem trocando ids no endereço.

## Mapa do projeto

```
app.py          fábrica da aplicação, hooks, erros, comandos de arranque
config.py       tudo o que muda entre ambientes
db.py           esquema + acesso a SQLite (todo o SQL passa por aqui)
security.py     sessão, CSRF, papéis e a origem única do business_id
services.py     dinheiro, slugs, uploads, assinaturas, WhatsApp, QR Code
blueprints/     public (catálogo), auth, business (painel), owner (plataforma)
templates/      public/ · auth/ · business/ · owner/
static/         style.css · cart.js
uploads/        imagens, uma pasta por empresa
```

## As três decisões que moldam o resto

**O `business_id` nunca vem do navegador.** Vem da sessão, por
`current_business_id()`. Todas as queries do painel levam `WHERE business_id = ?`.
É isto que impede a Empresa A de ler a Empresa B trocando um número no endereço —
não basta esconder botões na interface.

**Dinheiro é inteiro, em cêntimos.** `price_cents`, `total_cents`,
`amount_cents`. Vírgula flutuante em preços acumula erro e acaba em totais que
não fecham. A formatação para "5.000 Kz" acontece só na apresentação.

**Preços e totais são recalculados no servidor.** O navegador envia apenas ids e
quantidades. Se o total viesse do JavaScript, bastava abrir as ferramentas do
navegador para comprar um hambúrguer por 1 Kz.

## Estados da assinatura

`pending` · `active` · `expired` · `suspended` · `cancelled`

Quando expira: o catálogo público fecha, o painel fica limitado à página de
assinatura, e **nenhum dado é apagado**. A empresa envia o comprovativo, o
proprietário aprova, e tudo volta exactamente como estava. Renovar antes do
vencimento não perde dias — a nova assinatura começa onde a anterior acabava.

## Notas para a próxima fase

- **SQLite** aguenta bem uma fase inicial com escrita moderada. Como todo o SQL
  está em `db.py` e `services.py`, a migração para PostgreSQL é um trabalho
  localizado — principalmente trocar os `?` por `%s` e rever `ON CONFLICT`.
- **Pagamento manual** é propositado na v1. A tabela `payments` já guarda
  `reference`, `method` e `verified_at`, que é o que um gateway automático vai
  precisar de preencher em vez do proprietário.
- **PWA**: o manifest está servido em `/manifest.webmanifest`. Falta o service
  worker para o catálogo abrir sem rede.
- **Um utilizador por empresa** hoje. A tabela `users` já tem `business_id` e
  `role`, por isso vários funcionários por empresa é acrescentar papéis, não
  refazer o modelo.
