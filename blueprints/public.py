<div class="card-pedido" style="background: #fff; padding: 1.5rem; border-radius: 8px; margin-bottom: 1rem; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
    <strong>Pedido #{{ p.code }} - {{ p.customer_name }}</strong>
    <span class="badge status-{{ p.status }}">{{ p.status }}</span>
  </div>
  
  <p class="pequeno">Mesa/Contacto: {{ p.table_number or p.customer_phone }}</p>
  <p class="pequeno">Total: <strong>{{ p.total_cents }} Kz</strong></p>

  <!-- Área de Resposta Editável -->
  <div style="margin-top: 1rem; border-top: 1px solid #eee; padding-top: 1rem;">
    <label style="display: block; font-size: 0.85rem; font-weight: 600; margin-bottom: 0.5rem;">
      Mensagem de Resposta ao Cliente:
    </label>
    <textarea id="resposta-{{ p.id }}" rows="2" style="width: 100%; padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; font-size: 0.9rem;"
    >Muito obrigado pelo seu pedido! O seu pedido foi recebido com sucesso e estará pronto daqui a 10 minutos.</textarea>
    
    <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
      <select id="status-{{ p.id }}" style="padding: 0.4rem; border-radius: 4px; border: 1px solid #ccc;">
        <option value="em_preparacao">Em Preparação (10 min)</option>
        <option value="pronto">Pronto para Recolha/Entrega</option>
        <option value="concluido">Concluído</option>
      </select>
      
      <button type="button" onclick="enviarResposta({{ p.id }})" style="background: #0E6E5E; color: #fff; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-weight: 600;">
        Guardar e Notificar
      </button>
    </div>
  </div>
</div>

<script>
function enviarResposta(orderId) {
  var texto = document.getElementById("resposta-" + orderId).value;
  var status = document.getElementById("status-" + orderId).value;

  fetch("/owner/pedidos/" + orderId + "/responder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resposta: texto, status: status })
  })
  .then(function(res) { return res.json(); })
  .then(function(data) {
    if (data.ok) {
      alert("Resposta e estado atualizados com sucesso!");
      location.reload();
    } else {
      alert("Erro: " + (data.error || "Não foi possível guardar."));
    }
  })
  .catch(function(err) {
    console.error(err);
    alert("Erro de ligação.");
  });
}
</script>