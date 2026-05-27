import { defineStore } from "pinia";
import router from "@/router/router";
import { excelApiClient as apiClient } from "@/services/excelApi";
import { syncAuthToLangfuse } from "@/utils/langfuseBridge";

interface UserData {
  email: string;
  name?: string;
  role?: string;
  permissions?: string[];
  langfuse_enabled?: boolean;
}

export const Login = defineStore("login", {
  state: () => ({
    token: window.localStorage.getItem("user-token") || "",
    status: "",
    userData: null as UserData | null,
    isAuthenticated: !!window.localStorage.getItem("user-token"),
  }),
  persist: true,
  actions: {
    setUserData(data: UserData) {
      this.userData = data;
    },

    async login(identifier: string, password: string, companyId?: string): Promise<boolean> {
      this.status = "loading";
      try {
        const normalized = (identifier || "").trim().toLowerCase();
        const response = await apiClient.post("/api/auth/login", {
          email: normalized,
          loginId: normalized,
          companyId: companyId || "1JApYDzJ0P2ZXQYEVZKaJskYyVr",
          password,
        });

        const { token, name, role, permissions, langfuse_enabled } = response.data;

        window.localStorage.setItem("user-token", token);
        this.token = token;
        syncAuthToLangfuse(token);
        this.status = "success";
        this.isAuthenticated = true;
        this.setUserData({
          email: response.data?.email || normalized,
          name,
          role,
          permissions: permissions || [],
          langfuse_enabled,
        });

        return true;
      } catch (error: any) {
        this.status = "error";
        const errorMessage = error.response?.data?.detail || "Login failed";
        throw new Error(errorMessage);
      }
    },

    async register(email: string, username: string, password: string, name?: string): Promise<boolean> {
      this.status = "loading";
      try {
        const response = await apiClient.post("/api/auth/register", {
          email,
          username,
          password,
          name: name || username,
          role: "user",
        });

        const { token, name: userName, role, permissions, langfuse_enabled } = response.data;

        window.localStorage.setItem("user-token", token);
        this.token = token;
        syncAuthToLangfuse(token);
        this.status = "success";
        this.isAuthenticated = true;
        this.setUserData({
          email,
          name: userName,
          role,
          permissions: permissions || [],
          langfuse_enabled,
        });

        return true;
      } catch (error: any) {
        this.status = "error";
        const errorMessage = error.response?.data?.detail || "Registration failed";
        throw new Error(errorMessage);
      }
    },

    async fetchUserInfo(): Promise<boolean> {
      try {
        const response = await apiClient.get("/api/auth/me");
        const { email, name, role, permissions, langfuse_enabled } = response.data;

        this.setUserData({
          email,
          name,
          role,
          permissions,
          langfuse_enabled,
        });

        return true;
      } catch (error) {
        console.error("Failed to fetch user info:", error);
        return false;
      }
    },



    async logout() {
      try {
        await apiClient.post("/api/auth/logout");
      } catch (error) {
        console.error("Logout error:", error);
      } finally {
        this.status = "";
        this.token = "";
        this.userData = null;
        this.isAuthenticated = false;
        window.localStorage.removeItem("user-token");
        router.push("/login");
      }
    },

    hasPermission(permission: string): boolean {
      if (this.userData?.role === "admin") {
        return true;
      }
      return this.userData?.permissions?.includes(permission) || false;
    },
  },
});
