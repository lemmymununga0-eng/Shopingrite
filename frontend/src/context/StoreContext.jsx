import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import { useAuth } from "./AuthContext";

export const DEFAULT_STORE = {
  name: "FreshCart Demo Store", currency: "ZAR", is_demo: true, delivery_cities: [], delivery_fee_cents: 0,
  free_delivery_over_cents: 0, max_quantity_per_line: 20, local_auth_enabled: false,
  disclaimer: "Independent demonstration store with sample products and sample stock. Payments are simulated; no money is taken.",
};

const Ctx = createContext({ store: DEFAULT_STORE, cart: null, count: 0, refreshCart: async () => {}, setCart: () => {} });
export const useStore = () => useContext(Ctx);

/** Store identity (from the API, never hard-coded) and the signed-in shopper's server-side cart. */
export function StoreProvider({ children }) {
  const auth = useAuth();
  const userId = auth?.user?.id;
  const [store, setStore] = useState(DEFAULT_STORE);
  const [cart, setCart] = useState(null);

  useEffect(() => {
    let live = true;
    api.storeInfo?.().then(d => live && setStore({ ...DEFAULT_STORE, ...d })).catch(() => {});
    return () => { live = false; };
  }, []);

  const refreshCart = useCallback(async () => {
    if (!userId) { setCart(null); return null; }
    try { const c = await api.cart(); setCart(c); return c; }
    catch { return null; }
  }, [userId]);
  useEffect(() => { refreshCart(); }, [refreshCart]);

  const value = useMemo(() => ({ store, cart, count: cart?.item_count || 0, refreshCart, setCart }), [store, cart, refreshCart]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
