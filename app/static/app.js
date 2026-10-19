"use strict";

const $ = (id) => document.getElementById(id);
let busy = false;
let offset = 0;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch { throw new Error(`Request failed (${response.status}).`); }
  if (!response.ok) {
    const detail = data.detail;
    const error = new Error(typeof detail === "string" ? detail : Array.isArray(detail)
      ? detail.map((item) => item.msg).join("; ") : detail?.message || `Request failed (${response.status}).`);
    error.document = detail?.document;
    throw error;
  }
  return data;
}

function setBusy(value) {
  busy = value;
  for (const id of ["ask-button", "search-button", "upload-button", "refresh-button", "more-documents"]) $(id).disabled = value;
  for (const button of document.querySelectorAll(".index-button")) button.disabled = value;
  $("question-form").setAttribute("aria-busy", String(value));
}

function status(id, text, error = false) {
  $(id).textContent = text;
  $(id).classList.toggle("error", error);
}

async function indexDocument(document) {
  status("upload-status", `Preparing ${document.filename} for semantic search…`);
  await api(`/api/documents/${document.id}/index`, { method: "POST" });
}

function renderDocument(document) {
  const row = element("article", undefined, "document");
  row.append(element("p", document.filename, "document-name"));
  const ready = document.status === "ready";
  const indexed = document.embedding_status === "ready";
  const label = !ready ? document.status : indexed ? "Search ready" : "Text ready · index pending";
  row.append(element("span", label, `badge ${document.status === "error" ? "failed" : indexed ? "success" : "pending"}`));
  const size = document.size_bytes < 1024 ? `${document.size_bytes} B` : `${(document.size_bytes / 1024).toFixed(0)} KiB`;
  row.append(element("p", `${document.page_count} pages · ${document.chunk_count} fragments · ${size}`, "document-info"));
  if (document.error_message || document.embedding_error) row.append(element("p", document.error_message || document.embedding_error, "document-error"));
  if (ready && !indexed) {
    const button = element("button", document.embedding_status === "error" ? "Retry indexing" : "Prepare semantic search", "text-button index-button");
    button.type = "button";
    button.disabled = busy;
    button.addEventListener("click", async () => {
      if (busy) return;
      setBusy(true);
      try { await indexDocument(document); status("upload-status", `${document.filename} is search ready.`); }
      catch (error) { status("upload-status", error.message, true); }
      finally { await loadDocuments(); setBusy(false); }
    });
    row.append(button);
  }
  return row;
}

async function loadDocuments(append = false) {
  try {
    const documents = await api(`/api/documents?limit=20&offset=${append ? offset : 0}`);
    if (!append) { $("document-list").replaceChildren(); offset = 0; }
    offset += documents.length;
    if (!offset) $("document-list").append(element("p", "No documents yet. Add your first PDF or TXT above.", "empty-note"));
    for (const document of documents) $("document-list").append(renderDocument(document));
    $("more-documents").hidden = documents.length < 20;
  } catch (error) { status("upload-status", error.message, true); }
}

$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const files = [...$("files").files];
  if (!files.length) return;
  setBusy(true);
  const errors = [];
  let uploaded = 0;
  try {
    for (const [index, file] of files.entries()) {
      status("upload-status", `Uploading ${index + 1}/${files.length}: ${file.name}…`);
      const form = new FormData(); form.append("file", file);
      try {
        const document = await api("/api/documents", { method: "POST", body: form });
        uploaded += 1;
        if ($("auto-index").checked) await indexDocument(document);
      } catch (error) { errors.push(`${file.name}: ${error.message}`); }
      await loadDocuments();
    }
    status("upload-status", `${uploaded} document(s) uploaded.${errors.length ? " " + errors.join(" ") : " Ready for your question."}`, !!errors.length);
    $("files").value = "";
  } finally { setBusy(false); }
});

$("refresh-button").addEventListener("click", () => loadDocuments());
$("more-documents").addEventListener("click", () => loadDocuments(true));

function renderRetrieval(data) {
  $("retrieval-panel").hidden = false;
  $("retrieval-meta").textContent = `· ${data.mode}${data.reranked ? " + reranking" : ""} · ${data.elapsed_ms.toFixed(0)} ms`;
  $("retrieved-fragments").replaceChildren();
  if (!data.results.length) $("retrieved-fragments").append(element("p", "No matching fragments found.", "empty-note"));
  for (const [index, hit] of data.results.entries()) {
    const fragment = element("article", undefined, "fragment");
    fragment.append(element("div", `${index + 1}. ${hit.filename} · page ${hit.page_number}`, "fragment-heading"));
    fragment.append(element("pre", hit.text));
    const ranks = [hit.lexical_rank && `lexical #${hit.lexical_rank}`, hit.vector_rank && `vector #${hit.vector_rank}`, hit.rerank_rank && `reranked #${hit.rerank_rank}`].filter(Boolean);
    fragment.append(element("small", `Chunk ${hit.chunk_id} · score ${hit.score.toFixed(4)}${ranks.length ? " · " + ranks.join(" · ") : ""}`));
    $("retrieved-fragments").append(fragment);
  }
}

function renderWarnings(warnings) {
  $("warnings").replaceChildren(...warnings.map((warning) => element("p", warning, "warning")));
}

function renderAnswer(data) {
  $("answer").replaceChildren();
  $("answer-badge").textContent = data.abstained ? "Not enough evidence" : "Sources attached";
  $("answer-badge").className = `badge ${data.abstained ? "pending" : "success"}`;
  if (data.abstained) $("answer").append(element("p", data.answer, "abstention"));
  for (const claim of data.claims) {
    const card = element("article", undefined, "claim");
    card.append(element("p", claim.text, "claim-text"));
    for (const citation of claim.citations) {
      const details = element("details", undefined, "citation");
      details.append(element("summary", `${citation.filename} · page ${citation.page_number} ↗`));
      details.append(element("blockquote", citation.quote));
      card.append(details);
    }
    $("answer").append(card);
  }
  renderRetrieval(data.retrieval);
  renderWarnings(data.warnings);
  $("answer-meta").textContent = `${(data.elapsed_ms / 1000).toFixed(1)} s · ${data.model} · ${data.abstained ? "no supported answer produced" : "complete-sentence quotations matched to source text"}`;
}

async function runQuestion(searchOnly) {
  if (busy || !$("question-form").reportValidity()) return;
  const payload = { query: $("question").value.trim(), mode: $("mode").value, top_k: Number($("top-k").value), rerank: $("rerank").checked };
  if (!payload.query) { $("question").focus(); return; }
  setBusy(true);
  status("question-status", searchOnly ? "Finding source fragments…" : "Finding evidence and generating an answer locally. This may take a minute…");
  $("answer").replaceChildren(element("p", "Working on your question…", "empty-note"));
  $("warnings").replaceChildren();
  $("retrieval-panel").hidden = true;
  $("answer-meta").textContent = "";
  $("answer-badge").textContent = "Working…";
  $("answer-badge").className = "badge pending";
  try {
    const data = await api(searchOnly ? "/api/search" : "/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (searchOnly) {
      $("answer").replaceChildren(element("p", "Search results are ready below. Ask documents to generate an answer from this evidence.", "empty-note"));
      $("answer-meta").textContent = "";
      $("answer-badge").textContent = "Search results";
      $("answer-badge").className = "badge neutral";
      renderRetrieval(data); renderWarnings(data.warnings); $("retrieval-panel").open = true;
    } else renderAnswer(data);
    status("question-status", "");
  } catch (error) {
    status("question-status", error.message, true);
    $("answer").replaceChildren(element("p", "No answer was produced. Resolve the error and try again.", "empty-note"));
    $("answer-badge").textContent = "Request failed";
    $("answer-badge").className = "badge failed";
  } finally { setBusy(false); }
}

$("question-form").addEventListener("submit", (event) => { event.preventDefault(); runQuestion(false); });
$("search-button").addEventListener("click", () => runQuestion(true));
$("question").addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); runQuestion(false); } });
loadDocuments();
