"use client";

import type { ReactNode } from "react";
import { StoreProvider, ToastProvider } from "@/lib/store";
import { TabBar } from "./TabBar";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <StoreProvider>
      <ToastProvider>
        <main className="mx-auto min-h-dvh w-full max-w-md px-4 pb-28 pt-4">
          {children}
        </main>
        <TabBar />
      </ToastProvider>
    </StoreProvider>
  );
}
