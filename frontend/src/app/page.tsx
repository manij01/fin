"use client";

import { useState, useEffect, useCallback } from "react";
import Header from "@/components/Header";
import Panel from "@/components/Panel";
import ChatPanel from "@/components/ChatPanel";
import Watchlist from "@/components/Watchlist";
import MainChart from "@/components/MainChart";
import PortfolioHeatmap from "@/components/PortfolioHeatmap";
import PnlChart from "@/components/PnlChart";
import PositionsTable from "@/components/PositionsTable";
import TradeBar from "@/components/TradeBar";
import { useMarketData } from "@/hooks/useMarketData";
import { api, type PortfolioResponse } from "@/lib/api";

function usePortfolio() {
  const [portfolio, setPortfolio] = useState<PortfolioResponse>({
    cash_balance: 0,
    total_value: 0,
    positions: [],
  });

  const refresh = useCallback(async () => {
    try {
      const data = await api.getPortfolio();
      setPortfolio(data);
    } catch {
      // API not available yet
    }
  }, []);

  useEffect(() => {
    const id = setInterval(refresh, 15_000);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async data fetch on mount
    refresh();
    return () => clearInterval(id);
  }, [refresh]);

  return { portfolio, refresh };
}

export default function Home() {
  const { prices, connectionStatus, priceHistory } = useMarketData();
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [dataVersion, setDataVersion] = useState(0);
  const { portfolio, refresh: refreshPortfolio } = usePortfolio();
  const refreshDashboard = useCallback(() => {
    void refreshPortfolio();
    setDataVersion((version) => version + 1);
  }, [refreshPortfolio]);

  return (
    <div className="flex min-h-screen flex-col overflow-auto bg-bg-primary xl:h-screen xl:overflow-hidden">
      <Header
        totalValue={portfolio.total_value}
        cashBalance={portfolio.cash_balance}
        connectionStatus={connectionStatus}
      />

      <div className="flex min-h-0 flex-1 flex-col xl:flex-row">
        {/* Main content area */}
        <div className="flex min-h-[620px] min-w-[760px] flex-1 flex-col gap-1 p-1 xl:min-h-0">
          {/* Top row: watchlist + chart + portfolio */}
          <div className="flex min-h-0 flex-1 gap-1">
            {/* Watchlist */}
            <Panel title="Watchlist" className="w-60 shrink-0 overflow-auto lg:w-64">
              <Watchlist
                prices={prices}
                priceHistory={priceHistory}
                selectedTicker={selectedTicker}
                onSelectTicker={setSelectedTicker}
                refreshToken={dataVersion}
                onInitialTicker={setSelectedTicker}
                onWatchlistChanged={refreshDashboard}
              />
            </Panel>

            {/* Main chart */}
            <Panel title="Chart" className="min-w-0 flex-1">
              <MainChart
                ticker={selectedTicker}
                priceHistory={priceHistory}
              />
            </Panel>

            {/* Right column: portfolio views */}
            <div className="flex w-64 shrink-0 flex-col gap-1 lg:w-72">
              <Panel title="Portfolio Heatmap" className="flex-1">
                <PortfolioHeatmap positions={portfolio.positions} prices={prices} />
              </Panel>
              <Panel title="P&L" className="flex-1">
                <PnlChart refreshToken={dataVersion} />
              </Panel>
              <Panel title="Positions" className="flex-1 overflow-auto">
                <PositionsTable positions={portfolio.positions} prices={prices} />
              </Panel>
            </div>
          </div>

          {/* Trade bar */}
          <Panel title="Trade" className="min-h-14 shrink-0">
            <TradeBar onTradeExecuted={refreshDashboard} />
          </Panel>
        </div>

        {/* Chat sidebar */}
        <ChatPanel onDataRefresh={refreshDashboard} />
      </div>
    </div>
  );
}
