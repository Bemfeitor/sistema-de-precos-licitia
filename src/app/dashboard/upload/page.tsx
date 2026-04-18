"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import {
  CheckCircle2,
  Edit3,
  FileText,
  Loader2,
  Package,
  Sparkles,
  Upload,
} from "lucide-react";

const pagesPattern = /^\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*$/;

function isValidPagesConfig(value: string) {
  return value.trim().length === 0 || pagesPattern.test(value);
}

export default function UploadPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"pdf" | "manual">("pdf");
  const [file, setFile] = useState<File | null>(null);
  const [projectName, setProjectName] = useState("");
  const [pagesConfig, setPagesConfig] = useState("");
  const [manualProjectName, setManualProjectName] = useState("");
  const [manualProductName, setManualProductName] = useState("");
  const [manualQuantity, setManualQuantity] = useState("1");
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<Project | null>(null);
  const [error, setError] = useState("");

  const pageInputValid = useMemo(() => isValidPagesConfig(pagesConfig), [pagesConfig]);

  const handleFile = (candidate?: File | null) => {
    if (!candidate) {
      return;
    }

    if (candidate.type !== "application/pdf") {
      setError("Somente arquivos PDF são aceitos.");
      return;
    }

    setFile(candidate);
    setError("");
  };

  const handleUploadPdf = async () => {
    if (!file) {
      setError("Selecione um PDF para continuar.");
      return;
    }

    if (!pageInputValid) {
      setError("Informe as páginas no formato correto. Exemplo: 1, 3, 5-7.");
      return;
    }

    setUploading(true);
    setProgress(8);
    setError("");

    const progressTimer = window.setInterval(() => {
      setProgress((current) => (current >= 92 ? current : current + Math.random() * 6));
    }, 450);

    try {
      const data = await api.projects.upload(
        file,
        projectName.trim() || file.name.replace(/\.pdf$/i, ""),
        pagesConfig.trim()
      );

      window.clearInterval(progressTimer);
      setProgress(100);
      setResult(data);

      window.setTimeout(() => {
        router.push(`/dashboard/products?projectId=${data.id}`);
      }, 1600);
    } catch (err: unknown) {
      window.clearInterval(progressTimer);
      setError(err instanceof Error ? err.message : "Erro ao processar o PDF.");
      setProgress(0);
    } finally {
      setUploading(false);
    }
  };

  const handleUploadManual = async () => {
    if (!manualProductName.trim()) {
      setError("Informe pelo menos um produto para continuar.");
      return;
    }

    setUploading(true);
    setProgress(15);
    setError("");

    const progressTimer = window.setInterval(() => {
      setProgress((current) => (current >= 92 ? current : current + 12));
    }, 280);

    try {
      const data = await api.projects.uploadManual(
        manualProjectName.trim() || "Projeto Manual",
        manualProductName.trim(),
        Math.max(1, parseInt(manualQuantity, 10) || 1)
      );

      window.clearInterval(progressTimer);
      setProgress(100);
      setResult(data);

      window.setTimeout(() => {
        router.push(`/dashboard/products?projectId=${data.id}`);
      }, 1600);
    } catch (err: unknown) {
      window.clearInterval(progressTimer);
      setError(err instanceof Error ? err.message : "Erro ao criar o projeto manual.");
      setProgress(0);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: 24 }}>
      <motion.section
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card"
        style={{ padding: "clamp(1.25rem, 2.5vw, 2rem)" }}
      >
        <div style={{ display: "grid", gap: 18 }}>
          <span className="section-eyebrow">
            <Sparkles size={14} />
            Fluxo de entrada
          </span>

          <div style={{ display: "grid", gap: 10 }}>
            <h1 className="page-title">Importe listas e escolha exatamente quais páginas entram na coleta</h1>
            <p className="page-subtitle">
              O upload agora aceita seleção livre de páginas, com a mesma lógica de impressão:
              use `1, 3, 6` para páginas isoladas ou `2-7` para intervalos.
            </p>
          </div>
        </div>
      </motion.section>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
          gap: 24,
        }}
      >
        <section className="glass-card" style={{ padding: "clamp(1.25rem, 2.5vw, 2rem)" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 22 }}>
            <button className={mode === "pdf" ? "btn-primary" : "btn-secondary"} onClick={() => setMode("pdf")} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <FileText size={16} />
              Lista em PDF
            </button>
            <button className={mode === "manual" ? "btn-primary" : "btn-secondary"} onClick={() => setMode("manual")} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Edit3 size={16} />
              Digitar um item
            </button>
          </div>

          <AnimatePresence mode="wait">
            {mode === "pdf" ? (
              <motion.div
                key="pdf"
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -12 }}
                style={{ display: "grid", gap: 18 }}
              >
                <div style={{ display: "grid", gap: 8 }}>
                  <label style={{ fontWeight: 700 }}>Nome do projeto</label>
                  <input
                    value={projectName}
                    onChange={(event) => setProjectName(event.target.value)}
                    className="input-field"
                    placeholder="Ex: Pregão de suprimentos hospitalares"
                  />
                </div>

                <div style={{ display: "grid", gap: 8 }}>
                  <label style={{ fontWeight: 700 }}>Páginas para coletar os itens</label>
                  <input
                    value={pagesConfig}
                    onChange={(event) => setPagesConfig(event.target.value)}
                    className="input-field"
                    placeholder="Ex: 3, 5, 8-12"
                    style={{
                      borderColor: pagesConfig && !pageInputValid ? "rgba(251, 113, 133, 0.55)" : undefined,
                    }}
                  />
                  <div className="helper-text">
                    Aceita páginas separadas por vírgula ou intervalos: `1, 4, 7-10`. Se ficar em branco, o sistema tenta ler o PDF inteiro.
                  </div>
                </div>

                <div
                  onDragOver={(event) => {
                    event.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setDragging(false);
                    handleFile(event.dataTransfer.files?.[0]);
                  }}
                  onClick={() => document.getElementById("pdf-upload-input")?.click()}
                  className="glass-card"
                  style={{
                    padding: "clamp(1.5rem, 5vw, 3rem)",
                    border: `1px dashed ${dragging ? "rgba(56, 189, 248, 0.58)" : "rgba(148, 163, 184, 0.18)"}`,
                    background: dragging ? "rgba(56, 189, 248, 0.08)" : "rgba(7, 17, 31, 0.35)",
                    cursor: "pointer",
                    display: "grid",
                    placeItems: "center",
                    textAlign: "center",
                    gap: 14,
                  }}
                >
                  <div
                    style={{
                      width: 64,
                      height: 64,
                      borderRadius: 22,
                      background: "rgba(56, 189, 248, 0.12)",
                      display: "grid",
                      placeItems: "center",
                    }}
                  >
                    <Upload size={28} color="#67e8f9" />
                  </div>

                  <div>
                    <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 6 }}>
                      {file ? file.name : "Arraste o PDF aqui ou clique para selecionar"}
                    </div>
                    <div className="helper-text">PDFs de licitação, listas de itens ou documentos com tabelas de compra.</div>
                  </div>

                  <input
                    id="pdf-upload-input"
                    type="file"
                    accept="application/pdf"
                    hidden
                    onChange={(event) => handleFile(event.target.files?.[0])}
                  />
                </div>

                <button
                  onClick={handleUploadPdf}
                  disabled={uploading}
                  className="btn-primary"
                  style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, minHeight: 52 }}
                >
                  {uploading ? <Loader2 size={18} className="animate-spin" /> : <Upload size={18} />}
                  {uploading ? "Processando PDF..." : "Enviar PDF e extrair itens"}
                </button>
              </motion.div>
            ) : (
              <motion.div
                key="manual"
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -12 }}
                style={{ display: "grid", gap: 18 }}
              >
                <div style={{ display: "grid", gap: 8 }}>
                  <label style={{ fontWeight: 700 }}>Nome do projeto</label>
                  <input
                    value={manualProjectName}
                    onChange={(event) => setManualProjectName(event.target.value)}
                    className="input-field"
                    placeholder="Ex: Projeto piloto"
                  />
                </div>

                <div style={{ display: "grid", gap: 8 }}>
                  <label style={{ fontWeight: 700 }}>Produto</label>
                  <input
                    value={manualProductName}
                    onChange={(event) => setManualProductName(event.target.value)}
                    className="input-field"
                    placeholder="Ex: Caixa d'água em polietileno 1000 litros"
                  />
                </div>

                <div style={{ display: "grid", gap: 8, maxWidth: 220 }}>
                  <label style={{ fontWeight: 700 }}>Quantidade</label>
                  <input
                    value={manualQuantity}
                    onChange={(event) => setManualQuantity(event.target.value)}
                    className="input-field"
                    inputMode="numeric"
                    placeholder="1"
                  />
                </div>

                <button
                  onClick={handleUploadManual}
                  disabled={uploading}
                  className="btn-primary"
                  style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, minHeight: 52 }}
                >
                  {uploading ? <Loader2 size={18} className="animate-spin" /> : <Package size={18} />}
                  {uploading ? "Criando projeto..." : "Criar projeto manual"}
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </section>

        <aside style={{ display: "grid", gap: 16 }}>
          <section className="glass-card" style={{ padding: 20 }}>
            <div style={{ fontWeight: 700, marginBottom: 12 }}>Como preencher as páginas</div>
            <div style={{ display: "grid", gap: 10 }}>
              {[
                { example: "1, 3, 5", meaning: "coleta páginas isoladas" },
                { example: "4-9", meaning: "coleta do intervalo 4 até 9" },
                { example: "2-4, 8, 11-12", meaning: "combina intervalos e páginas avulsas" },
              ].map((item) => (
                <div key={item.example} className="glass-card" style={{ padding: 14 }}>
                  <div style={{ fontWeight: 700, marginBottom: 4 }}>{item.example}</div>
                  <div className="helper-text">{item.meaning}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="glass-card" style={{ padding: 20 }}>
            <div style={{ fontWeight: 700, marginBottom: 12 }}>Status do processamento</div>

            {uploading && (
              <div style={{ display: "grid", gap: 12 }}>
                <div style={{ height: 10, borderRadius: 999, background: "rgba(148, 163, 184, 0.12)", overflow: "hidden" }}>
                  <div
                    style={{
                      width: `${progress}%`,
                      height: "100%",
                      background: "var(--gradient-primary)",
                      transition: "width 0.25s ease",
                    }}
                  />
                </div>
                <div className="helper-text">Preparando extração, interpretando o documento e sincronizando os itens.</div>
              </div>
            )}

            {!uploading && result && (
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 12,
                  padding: 16,
                  borderRadius: 16,
                  background: "rgba(52, 211, 153, 0.1)",
                  border: "1px solid rgba(52, 211, 153, 0.18)",
                }}
              >
                <CheckCircle2 size={20} color="#86efac" />
                <div>
                  <div style={{ fontWeight: 700 }}>Projeto criado com sucesso</div>
                  <div className="helper-text" style={{ marginTop: 4 }}>
                    Status atual: {result.status}. Você será redirecionado para revisar os itens do projeto.
                  </div>
                </div>
              </div>
            )}

            {!uploading && error && (
              <div
                style={{
                  padding: 16,
                  borderRadius: 16,
                  background: "rgba(251, 113, 133, 0.1)",
                  border: "1px solid rgba(251, 113, 133, 0.18)",
                  color: "#fecdd3",
                  lineHeight: 1.5,
                }}
              >
                {error}
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
