/* Carrinho do catálogo público.
 *
 * O carrinho vive só no navegador. Os preços aqui servem apenas para
 * mostrar o total ao cliente — quem decide quanto custa é o servidor,
 * que recalcula tudo a partir da base de dados ao receber o pedido.
 */
(function () {
  "use strict";

  var cfg = window.NEXORA || {};
  var carrinho = new Map(); // id -> {id, nome, preco, qtd}

  var barra = document.getElementById("barra");
  var barraItens = document.getElementById("barra-itens");
  var barraTotal = document.getElementById("barra-total");
  var folha = document.getElementById("folha");
  var lista = document.getElementById("lista-carrinho");
  var totalEl = document.getElementById("total-carrinho");
  var estado = document.getElementById("estado-envio");
  var btnEnviar = document.getElementById("enviar");

  function formatar(cents) {
    var inteiro = Math.floor(Math.abs(cents) / 100);
    var resto = Math.abs(cents) % 100;
    var txt = inteiro.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    if (resto) txt += "," + String(resto).padStart(2, "0");
    return txt + " " + (cfg.moeda || "Kz");
  }

  function totais() {
    var itens = 0, total = 0;
    carrinho.forEach(function (i) { itens += i.qtd; total += i.qtd * i.preco; });
    return { itens: itens, total: total };
  }

  function pintar() {
    var t = totais();
    barraItens.textContent = t.itens === 1 ? "1 item" : t.itens + " itens";
    barraTotal.textContent = formatar(t.total);
    barra.classList.toggle("visivel", t.itens > 0);
    totalEl.textContent = formatar(t.total);

    document.querySelectorAll(".produto").forEach(function (card) {
      var id = card.dataset.id;
      var item = carrinho.get(id);
      card.querySelector("[data-valor]").textContent = item ? item.qtd : 0;
    });

    lista.innerHTML = "";
    if (!carrinho.size) {
      lista.innerHTML =
        '<div class="vazio" style="padding:1.5rem"><strong>Carrinho vazio</strong>' +
        '<div class="pequeno">Escolha produtos no catálogo para começar.</div></div>';
      btnEnviar.disabled = true;
      return;
    }
    btnEnviar.disabled = false;

    carrinho.forEach(function (item) {
      var linha = document.createElement("div");
      linha.className = "linha-carrinho";
      linha.innerHTML =
        '<div class="info"><div style="font-weight:600">' + escapar(item.nome) + "</div>" +
        '<div class="pequeno mudo">' + formatar(item.preco) + " cada</div></div>" +
        '<div class="qtd">' +
        '<button type="button" data-linha="menos" aria-label="Retirar um">−</button>' +
        '<span class="valor">' + item.qtd + "</span>" +
        '<button type="button" data-linha="mais" aria-label="Juntar um">+</button>' +
        "</div>" +
        '<div style="font-weight:700;min-width:5.5rem;text-align:right">' +
        formatar(item.qtd * item.preco) + "</div>";
      linha.querySelector('[data-linha="menos"]').onclick = function () {
        mudar(item.id, -1);
      };
      linha.querySelector('[data-linha="mais"]').onclick = function () {
        mudar(item.id, 1);
      };
      lista.appendChild(linha);
    });
  }

  function escapar(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function mudar(id, delta) {
    var numId = Number(id);
    var item = carrinho.get(numId) || carrinho.get(id);

    if (!item) {
        if (delta < 0) return;
        
        // Tenta encontrar o elemento na página de forma flexível
        var card = document.querySelector('.produto[data-id="' + id + '"]') || 
                   document.querySelector('[data-id="' + id + '"]') ||
                   document.querySelector('.produto[data-produto-id="' + id + '"]');
                   
        if (!card) {
            // Se não encontrar o card visual, cria um item básico com o ID
            item = { id: id, nome: "Produto #" + id, preco: 0, qtd: 0 };
        } else {
            item = {
                id: id,
                nome: card.dataset.nome || "Produto",
                preco: Number(card.dataset.preco) || 0,
                qtd: 0
            };
        }
    }
item.qtd += delta;

    if (item.qtd <= 0) {
        carrinho.delete(id);
        carrinho.delete(numId);
    } else {
        carrinho.set(id, item);
    }
    totais();
    pintar();
}

  document.querySelectorAll(".produto").forEach(function (card) {
    var id = card.dataset.id;
    card.querySelector('[data-acao="mais"]').onclick = function () { mudar(id, 1); };
    card.querySelector('[data-acao="menos"]').onclick = function () { mudar(id, -1); };
  });

  function abrir() { folha.classList.add("aberta"); document.body.style.overflow = "hidden"; }
  function fechar() { folha.classList.remove("aberta"); document.body.style.overflow = ""; }

  document.getElementById("abrir-carrinho").onclick = abrir;
  folha.querySelectorAll("[data-fechar]").forEach(function (el) { el.onclick = fechar; });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && folha.classList.contains("aberta")) fechar();
  });

 btnEnviar.onclick = function () {
    if (!carrinho.size) {
        alert("O carrinho está vazio.");
        return;
    }
    
    var itens = [];
    carrinho.forEach(function (i) { 
        itens.push({ id: Number(i.id), qty: i.qtd }); 
    });

    btnEnviar.disabled = true;
    estado.textContent = "A registar o pedido...";

    fetch(cfg.endpointPedido, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            itens: itens,
            name: valor("f-nome"),
            phone: valor("f-telefone"),
            table: valor("f-mesa"),
            observacao: valor("f-obs") || ""
        })
    })
    .then(function (res) {
        if (!res.ok) {
            throw new Error("Erro ao enviar pedido");
        }
        return res.json();
    })
    .then(function (res) {
        estado.textContent = "Pedido #" + res.code + " registado com sucesso no painel!";
        btnEnviar.disabled = true;
        // Limpar o carrinho e recarregar ou fechar modal após 2 segundos
        setTimeout(function() {
            location.reload();
        }, 2000);
    })
    .catch(function (err) {
        console.error(err);
        estado.textContent = "Erro ao enviar. Verifique os dados e tente de novo.";
        btnEnviar.disabled = false;
    });
};
        notes: valor("f-obs"),
        payment_method: valor("f-pagamento")
      })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok || !res.d.ok) {
          estado.textContent = res.d.error || "Não foi possível registar o pedido.";
          btnEnviar.disabled = false;
          return;
        }
        if (res.d.whatsapp_url) {
          estado.textContent = "Pedido " + res.d.code + " registado. A abrir o WhatsApp...";
          window.location.href = res.d.whatsapp_url;
        } else {
          // Sem número de WhatsApp configurado: mostramos o pedido para copiar.
          estado.innerHTML =
            "Pedido <strong>" + res.d.code + "</strong> registado. " +
            "Este estabelecimento ainda não tem WhatsApp configurado — " +
            "mostre este código no balcão.";
          btnEnviar.disabled = true;
        }
      })
      .catch(function () {
        estado.textContent = "Sem ligação. Verifique a internet e tente de novo.";
        btnEnviar.disabled = false;
      });
  };

  function valor(id) {
    var el = document.getElementById(id);
    return el ? el.value.trim() : "";
  }

  pintar();
})();
