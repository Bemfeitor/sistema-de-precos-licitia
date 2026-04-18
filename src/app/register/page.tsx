"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowRight, Eye, EyeOff, Sparkles } from "lucide-react";
import { useAuth } from "@/lib/auth";

export default function RegisterPage() {
    const router = useRouter();
    const { register } = useAuth();
    const [name, setName] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [showPassword, setShowPassword] = useState(false);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        setError("");

        if (password.length < 6) {
            setError("A senha deve ter pelo menos 6 caracteres.");
            return;
        }

        setLoading(true);
        try {
            await register(email, name, password);
            router.push("/dashboard");
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : "Erro ao criar conta");
        } finally {
            setLoading(false);
        }
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
                        <span className="section-eyebrow">
                            <Sparkles size={14} />
                            Novo workspace
                        </span>

                        <div>
                            <h1 className="page-title">Crie sua conta e comece a estruturar a operação</h1>
                            <p className="page-subtitle" style={{ marginTop: 12 }}>
                                Em poucos minutos você sobe um PDF, separa as páginas certas e transforma uma lista bruta em orçamento acionável.
                            </p>
                        </div>
                    </section>

                    <section style={{ padding: "clamp(1.5rem, 5vw, 3rem)", display: "grid", gap: 20 }}>
                        <div>
                            <div className="gradient-text" style={{ fontSize: 28, fontWeight: 700 }}>
                                Criar conta
                            </div>
                            <p style={{ color: "var(--text-secondary)", marginTop: 8 }}>
                                Configure seu acesso e entre no fluxo principal do sistema.
                            </p>
                        </div>

                        <form onSubmit={handleSubmit} style={{ display: "grid", gap: 16 }}>
                            <div style={{ display: "grid", gap: 8 }}>
                                <label style={{ fontWeight: 600 }}>Nome completo</label>
                                <input
                                    type="text"
                                    value={name}
                                    onChange={(event) => setName(event.target.value)}
                                    className="input-field"
                                    placeholder="Seu nome"
                                    required
                                />
                            </div>

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
                                        placeholder="Mínimo de 6 caracteres"
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
                                {loading ? "Criando conta..." : "Criar conta"}
                                {!loading && <ArrowRight size={18} />}
                            </button>
                        </form>

                        <div style={{ color: "var(--text-secondary)", fontSize: 14 }}>
                            Já tem conta?{" "}
                            <Link href="/login" style={{ color: "var(--accent)", fontWeight: 700 }}>
                                Fazer login
                            </Link>
                        </div>
                    </section>
                </div>
            </motion.div>
        </div>
    );
}
