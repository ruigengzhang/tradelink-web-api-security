"use strict";

const login = document.querySelector("#login");
const workspace = document.querySelector("#workspace");
const search = document.querySelector("#search");
const productStatus = document.createElement("p");
productStatus.setAttribute("role", "status");
search.after(productStatus);
const notice = document.querySelector("#notice");
const products = document.querySelector("#products");
const orders = document.querySelector("#orders");
let accessToken = null;

async function api(path, { method = "GET", data, token = accessToken } = {}) {
  const headers = {};
  if (token) headers.Authorization = "Bearer " + token;
  if (data) headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    method, headers, body: data ? JSON.stringify(data) : undefined
  });
  if (!response.ok) throw new Error("Request failed (HTTP " + response.status + ").");
  if (response.status !== 204) return response.json();
}

function renderList(list, values) {
  list.replaceChildren();
  for (const value of values.length ? values : ["No results."]) {
    const item = document.createElement("li");
    item.textContent = value;
    list.append(item);
  }
}

async function showProducts(token, query = "") {
  const { items } = await api("/products?q=" + encodeURIComponent(query), { token });
  if (token !== accessToken) return;
  renderList(products, items.map(item =>
    item.name + " — USD " + (item.price_cents / 100).toFixed(2)
  ));
  return items.length;
}

login.addEventListener("submit", async event => {
  event.preventDefault();
  const button = login.querySelector("button");
  button.disabled = true;
  notice.textContent = "";
  try {
    const data = Object.fromEntries(new FormData(login));
    const session = await api("/auth/login", { method: "POST", data });
    accessToken = session.access_token;
    login.reset();
    login.hidden = true;
    document.querySelector("#role").textContent = "Signed in as " + session.role + ".";
    const { items } = await api("/orders", { token: session.access_token });
    if (session.access_token !== accessToken) return;
    renderList(orders, items.map(item =>
      "Order #" + item.id + " — " + item.quantity + " units — " + item.status
    ));
    await showProducts(session.access_token);
  } catch (error) {
    notice.textContent = error.message;
  } finally {
    workspace.hidden = !accessToken;
    button.disabled = false;
  }
});

search.addEventListener("submit", async event => {
  event.preventDefault();
  const token = accessToken;
  const button = search.querySelector("button");
  const query = new FormData(search).get("q");
  button.disabled = true;
  productStatus.textContent = "Searching…";
  try {
    const count = await showProducts(token, query);
    if (token !== accessToken) return;
    const label = count === 1 ? "product" : "products";
    const filter = query ? " for “" + query + "”" : "";
    productStatus.textContent = "Found " + count + " " + label + filter + ".";
  } catch (error) {
    if (token === accessToken) productStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#logout").addEventListener("click", async event => {
  const button = event.currentTarget;
  button.disabled = true;
  notice.textContent = "";
  try {
    await api("/auth/logout", { method: "POST" });
  } catch (error) {
    notice.textContent = "Local sign-out completed. " + error.message;
  } finally {
    accessToken = null;
    products.replaceChildren();
    orders.replaceChildren();
    search.reset();
    productStatus.textContent = "";
    workspace.hidden = true;
    login.hidden = false;
    button.disabled = false;
  }
});
