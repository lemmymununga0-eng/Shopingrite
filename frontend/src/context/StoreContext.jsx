import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import { useAuth } from "./AuthContext";

export const DEFAULT_STORE = {
  name: "Online store", legal_name: "", currency: "ZMW", is_demo: false, delivery_cities: [], delivery_fee_cents: 0,
  free_delivery_over_cents: 0, max_quantity_per_line: 20, local_auth_enabled: false, console_admin_only: false, disclaimer: "",
  contact_email: "", contact_phone: "", contact_address: "",
};

const Ctx = createContext({ store: DEFAULT_STORE, cart: null, count: 0, categories: [], cartLookup: new Map(), drawerOpen: false,
  openDrawer: () => {}, closeDrawer: () => {}, refreshCart: async () => {}, setCart: () => {} });
export const useStore = () => useContext(Ctx);

/** Store identity (from the API, never hard-coded), the category list, and the signed-in shopper's server-side cart. */
export function StoreProvider({ children }) {
  const auth = useAuth();
  const userId = auth?.user?.id;
  const [store, setStore] = useState(DEFAULT_STORE);
  const [cart, setCart] = useState(null);
  const [categories, setCategories] = useState([]);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.resolve(api.storeInfo?.()).then(d => live && d && setStore({ ...DEFAULT_STORE, ...d })).catch(() => {});
    Promise.resolve(api.categories?.()).then(c => live && Array.isArray(c) && setCategories(c)).catch(() => {});
    return () => { live = false; };
  }, []);

  const refreshCart = useCallback(async () => {
    if (!userId) { setCart(null); return null; }
    try { const c = await api.cart(); setCart(c); return c; }
    catch { return null; }
  }, [userId]);
  useEffect(() => { refreshCart(); }, [refreshCart]);

  // product id -> { itemId, quantity }: lets every product card show a quantity stepper when the item is already in the cart
  const cartLookup = useMemo(() => {
    const m = new Map();
    (cart?.items || []).forEach(l => m.set(l.product.id, { itemId: l.item_id, quantity: l.quantity }));
    return m;
  }, [cart]);

  const value = useMemo(() => ({
    store, cart, count: cart?.item_count || 0, categories, cartLookup, drawerOpen,
    openDrawer: () => setDrawerOpen(true), closeDrawer: () => setDrawerOpen(false), refreshCart, setCart,
  }), [store, cart, categories, cartLookup, drawerOpen, refreshCart]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
