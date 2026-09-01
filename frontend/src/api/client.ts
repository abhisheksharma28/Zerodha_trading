import axios from "axios";

const baseURL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api/v1";

export const apiClient = axios.create({ baseURL });

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // Backend's AppError handler always returns {code, message, details} —
    // surface `message` consistently so UI error states don't have to know
    // about axios's error shape.
    const body = error?.response?.data as ApiErrorBody | undefined;
    if (body?.message) {
      error.message = body.message;
    }
    return Promise.reject(error);
  },
);
