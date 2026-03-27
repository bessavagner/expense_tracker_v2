function getCsrfToken(): string {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : "";
}

export async function fetchApi<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: {
      "X-CSRFToken": getCsrfToken(),
      Accept: "application/json",
    },
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  return response.json();
}
