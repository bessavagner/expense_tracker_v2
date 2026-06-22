import { useEffect, useState } from "react";
import { fetchApi } from "./api";

/**
 * Busca `apiUrl` na montagem e refaz a busca quando o evento global
 * `data-changed` dispara (assistente alterou dados). Retorna null até a
 * primeira carga. Centraliza a reatividade dos cards do dashboard (item #5).
 */
export function useApiData<T>(apiUrl: string): T | null {
  const [data, setData] = useState<T | null>(null);

  useEffect(() => {
    if (!apiUrl) return;
    let active = true;
    const load = () => {
      fetchApi<T>(apiUrl).then((d) => {
        if (active) setData(d);
      });
    };
    load();
    window.addEventListener("data-changed", load);
    return () => {
      active = false;
      window.removeEventListener("data-changed", load);
    };
  }, [apiUrl]);

  return data;
}
