"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowRight, Eye, EyeOff, Server, Sparkles } from "lucide-react";
import { API_URL } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type ApiStatus = "checking" | "online" | "offline";

export default function LoginPage() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const { login } = useAuth();
    const [email, setEmail] = useState("test@example.com");
    const [password, setPassword] = useState("test123");
    const [showPassword, setShowPassword] = useState(false);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);
    const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");

    useEffect(() => {
        void checkApiStatus();
    }, []);

    useEffect(() => {
        if (searchParams.get("reason") === "session-expired") {
            setError("Sua sessão expirou. Faça login novamente.");
        }
    }, [searchParams]);

    const checkApiStatus = async () => {
        try {
            const response = await fetch(`${API_URL}/api/health`);
            setApiStatus(response.ok ? "online" : "offline");
        } catch {
            setApiStatus("offline");
        }
    };

    const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        setError("");
        setLoading(true);

        try {
            await login(email, password);
            router.push(searchParams.get("next") || "/dashboard");
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : "Erro ao fazer login";
            if (message.includes("Email ou senha")) {
                setError("Email ou senha incorretos.");
            } else if (message.includes("sessão expirou")) {
                setError("Sua sessão expirou. Faça login novamente.");
            } else if (message.includes("conectar")) {
                setApiStatus("offline");
                setError(`Não foi possível conectar ao backend em ${API_URL}.`);
            } else {
                setError(message);
            }
        } finally {
            setLoading(false);
        }
    };

    const enterDemoMode = () => {
        localStorage.setItem("token", "demo-token");
        localStorage.setItem(
            "user",
            JSON.stringify({
                id: "demo-user",
                email: "demo@example.com",
                name: "Usuário Demo",
            })
        );
        router.push("/dashboard");
    };

    return (
        <div className="auth-shell">
            <motion.div
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: 1, y: 0 }}
                className="glass-card"
                style={{ width: "min(100%, 1080px)", overflow: "hidden" }}
            >
                <div
                    style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
                    }}
                >
                    <section
                        style={{
                            padding: "clamp(1.5rem, 5vw, 3rem)",
                            background: "linear-gradient(160deg, rgba(8, 33, 51, 0.96), rgba(7, 17, 31, 0.92))",
                            display: "grid",
                            gap: 18,
                            alignContent: "space-between",
                        }}
                    >
                        <div style={{ display: "grid", gap: 18 }}>
                            <span className="section-eyebrow">
                                <Sparkles size={14} />
                                Acesso seguro
                            </span>
                            <div>
                                <h1 className="page-title">Entre no cockpit da sua operação de cotação</h1>
                                <p className="page-subtitle" style={{ marginTop: 12 }}>
                                    Suba PDFs, selecione páginas, compare ofertas e feche orçamentos em um fluxo único.
                                </p>
                            </div>
                        </div>

                        <div style={{ display: "grid", gap: 12 }}>
                            {[
                                "Upload de PDF com seleção de páginas",
                                "Busca consolidada em marketplaces",
                                "Análise, aprovação e geração de orçamentos",
                            ].map((item) => (
                                <div key={item} className="glass-card" style={{ padding: 14 }}>
                                    <div style={{ fontWeight: 600 }}>{item}</div>
                                </div>
                            ))}
                        </div>
                    </section>

                    <section style={{ padding: "clamp(1.5rem, 5vw, 3rem)", display: "grid", gap: 20 }}>
                        <div>
                            <div className="gradient-text" style={{ fontSize: 28, fontWeight: 700 }}>
                                Preço Inteligente
                            </div>
                            <p style={{ color: "var(--text-secondary)", marginTop: 8 }}>
                                Use sua conta para continuar do ponto onde parou.
                            </p>
                        </div>

                        <div
                            style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 8,
                                padding: "10px 14px",
                                borderRadius: 999,
                                width: "fit-content",
                                background:
                                    apiStatus === "online"
                                        ? "rgba(52, 211, 153, 0.12)"
                                        : apiStatus === "offline"
                                            ? "rgba(251, 113, 133, 0.12)"
                                            : "rgba(56, 189, 248, 0.12)",
                                border:
                                    apiStatus === "online"
                                        ? "1px solid rgba(52, 211, 153, 0.22)"
                                        : apiStatus === "offline"
                                            ? "1px solid rgba(251, 113, 133, 0.22)"
                                            : "1px solid rgba(56, 189, 248, 0.22)",
                            }}
                        >
                            <Server size={14} />
                            <span style={{ fontSize: 13, fontWeight: 600 }}>
                                API {apiStatus === "online" ? "online" : apiStatus === "offline" ? "offline" : "verificando"}
                            </span>
                            <button type="button" onClick={() => void checkApiStatus()} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer" }}>
                                Atualizar
                            </button>
                        </div>

                        <form onSubmit={handleSubmit} style={{ display: "grid", gap: 16 }}>
                            <div style={{ display: "grid", gap: 8 }}>
                                <label style={{ fontWeight: 600 }}>Email</label>
                                <input
                                    type="email"
                                    value={email}
                                    onChange={(event) => setEmail(event.target.value)}
                                    className="input-field"
                                    placeholder="seu@email.com"
                                    required
                                />
                            </div>

                            <div style={{ display: "grid", gap: 8 }}>
                                <label style={{ fontWeight: 600 }}>Senha</label>
                                <div style={{ position: "relative" }}>
                                    <input
                                        type={showPassword ? "text" : "password"}
                                        value={password}
                                        onChange={(event) => setPassword(event.target.value)}
                                        className="input-field"
                                        placeholder="Digite sua senha"
                                        style={{ paddingRight: 48 }}
                                        required
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowPassword((current) => !current)}
                                        style={{
                                            position: "absolute",
                                            top: "50%",
                                            right: 14,
                                            transform: "translateY(-50%)",
                                            background: "none",
                                            border: "none",
                                            color: "var(--text-muted)",
                                            cursor: "pointer",
                                        }}
                                    >
                                        {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                                    </button>
                                </div>
                            </div>

                            {error && (
                                <div style={{ padding: "12px 14px", borderRadius: 14, background: "rgba(251, 113, 133, 0.12)", color: "#fecdd3" }}>
                                    {error}
                                </div>
                            )}

                            <button type="submit" disabled={loading} className="btn-primary" style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 52 }}>
                                {loading ? "Entrando..." : "Entrar"}
                                {!loading && <ArrowRight size={18} />}
                            </button>

                            {apiStatus === "offline" && (
                                <button type="button" onClick={enterDemoMode} className="btn-secondary" style={{ minHeight: 50 }}>
                                    Entrar em modo demo
                                </button>
                            )}
                        </form>

                        <div style={{ color: "var(--text-secondary)", fontSize: 14 }}>
                            Não tem conta?{" "}
                            <Link href="/register" style={{ color: "var(--accent)", fontWeight: 700 }}>
                                Cadastre-se
                            </Link>
                        </div>
                    </section>
                </div>
            </motion.div>
        </div>
    );
}
