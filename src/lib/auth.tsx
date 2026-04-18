"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { AUTH_EXPIRED_EVENT, api } from "./api";
import type { AuthResponse, User } from "./types";

interface AuthContextType {
    user: User | null;
    token: string | null;
    isLoading: boolean;
    login: (email: string, password: string) => Promise<void>;
    register: (email: string, name: string, password: string) => Promise<void>;
    logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function clearStoredSession() {
    if (typeof window === "undefined") {
        return;
    }

    localStorage.removeItem("token");
    localStorage.removeItem("user");
}

function readStoredUser(value: string | null) {
    if (!value) {
        return null;
    }

    try {
        return JSON.parse(value) as User;
    } catch (error) {
        console.error("Erro ao ler usuário salvo", error);
        return null;
    }
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [token, setToken] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        const resetSession = () => {
            clearStoredSession();
            setToken(null);
            setUser(null);
        };

        const savedToken = localStorage.getItem("token");
        const savedUser = localStorage.getItem("user");

        window.addEventListener(AUTH_EXPIRED_EVENT, resetSession);

        if (!savedToken) {
            Promise.resolve().then(() => setIsLoading(false));
            return () => window.removeEventListener(AUTH_EXPIRED_EVENT, resetSession);
        }

        const parsedUser = readStoredUser(savedUser);
        Promise.resolve().then(() => {
            setToken(savedToken);
            if (parsedUser) {
                setUser(parsedUser);
            }
        });

        if (savedToken === "demo-token") {
            Promise.resolve().then(() => setIsLoading(false));
            return () => window.removeEventListener(AUTH_EXPIRED_EVENT, resetSession);
        }

        api.auth
            .me()
            .then((data) => {
                setUser(data);
                localStorage.setItem("user", JSON.stringify(data));
            })
            .catch(() => {
                resetSession();
            })
            .finally(() => setIsLoading(false));

        return () => window.removeEventListener(AUTH_EXPIRED_EVENT, resetSession);
    }, []);

    const persistSession = (data: AuthResponse) => {
        localStorage.setItem("token", data.access_token);
        localStorage.setItem("user", JSON.stringify(data.user));
        setToken(data.access_token);
        setUser(data.user);
    };

    const login = async (email: string, password: string) => {
        const data = await api.auth.login({ email, password });
        persistSession(data);
    };

    const register = async (email: string, name: string, password: string) => {
        const data = await api.auth.register({ email, name, password });
        persistSession(data);
    };

    const logout = () => {
        clearStoredSession();
        setToken(null);
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{ user, token, isLoading, login, register, logout }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error("useAuth must be used within AuthProvider");
    }

    return context;
}
