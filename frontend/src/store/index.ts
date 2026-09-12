/** The store: RTK Query for anything with a settled result, slices for the rest. */
import { configureStore } from "@reduxjs/toolkit";

import { apiSlice } from "../api/apiSlice";
import authReducer from "./authSlice";
import chatReducer, { bindTokenReader } from "./chatSlice";
import modelsReducer from "./modelsSlice";
import uiReducer from "./uiSlice";

export const store = configureStore({
  reducer: {
    [apiSlice.reducerPath]: apiSlice.reducer,
    auth: authReducer,
    chat: chatReducer,
    models: modelsReducer,
    ui: uiReducer,
  },
  middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(apiSlice.middleware),
});

// Lets the streaming thunk read the freshly-refreshed token without
// importing the store into the slice, which would be a cycle.
bindTokenReader(() => store.getState().auth.accessToken);

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
