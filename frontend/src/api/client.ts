import axios from "axios";

export const TOKEN_KEY = "jwt_token";
export const USER_KEY = "user_name";
export const ROLE_KEY = "user_role";

export const api = axios.create({
  baseURL: "/",
  timeout: 30_000,
});

// Auto-attach JWT vào mọi request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-redirect khi 401 (token hết hạn / sai)
api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      localStorage.removeItem(ROLE_KEY);
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);
