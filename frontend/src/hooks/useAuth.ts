import { useEffect, useState } from "react";
import { api, TOKEN_KEY, USER_KEY, ROLE_KEY } from "@/api/client";

export interface CurrentUser {
  id: number;
  username: string;
  role: "USER" | "ADMIN";
  is_active: boolean;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredRole(): string {
  return localStorage.getItem(ROLE_KEY) || "USER";
}

export function getStoredUsername(): string {
  return localStorage.getItem(USER_KEY) || "User";
}

export async function login(username: string, password: string): Promise<CurrentUser> {
  const { data } = await api.post<{ access_token: string }>("/auth/login", {
    username,
    password,
  });
  localStorage.setItem(TOKEN_KEY, data.access_token);

  const me = await api.get<CurrentUser>("/auth/me");
  localStorage.setItem(USER_KEY, me.data.username);
  localStorage.setItem(ROLE_KEY, me.data.role);
  return me.data;
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(ROLE_KEY);
  window.location.href = "/login";
}

export function useAuth() {
  const [role, setRole] = useState<string>(getStoredRole());
  const [username, setUsername] = useState<string>(getStoredUsername());

  useEffect(() => {
    const handler = () => {
      setRole(getStoredRole());
      setUsername(getStoredUsername());
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  return {
    username,
    role,
    isAuthenticated: !!getToken(),
    isAdmin: role === "ADMIN",
    logout,
  };
}
