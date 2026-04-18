'use client';

import { useState, useEffect } from 'react';
import { api, API_URL } from '@/lib/api';
import type { Offer, Product } from '@/lib/types';

interface Item {
  id: string;
  item_number: number;
  name: string;
  description: string;
  quantity: number;
  unit_price_max: number;
  total_price_max: number;
  status: 'PENDING' | 'ANALYZING' | 'APPROVED' | 'DISCARDED' | 'SUCCESS' | 'ERROR' | 'ERROR_NOT_FOUND';
  offers: Offer[];
  market_price?: number;
  recommended_price?: number;
  margin?: number;
}

type ItemStatus = Item['status'];

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Erro ao carregar dados';
}

function mapProductStatus(status: string): ItemStatus {
  switch (status) {
    case 'SUCCESS':
    case 'APPROVED':
      return 'APPROVED';
    case 'DISCARDED':
    case 'ERROR_NOT_FOUND':
      return 'DISCARDED';
    case 'ANALYZING':
      return 'ANALYZING';
    case 'ERROR':
      return 'ERROR';
    default:
      return 'PENDING';
  }
}

export default function ObsidianProcurement() {
  const [items, setItems] = useState<Item[]>([]);
  const [selectedItem, setSelectedItem] = useState<Item | null>(null);
  const [loading, setLoading] = useState(true);
  const [projectId, setProjectId] = useState<string>('');
  const [cmv, setCmv] = useState<number>(0);
  const [margin, setMargin] = useState<number>(30);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Carregar itens do projeto
  useEffect(() => {
    loadItems();
  }, []);

  const loadItems = async () => {
    try {
      setError(null);
      const projectsResponse = await api.projects.list();
      const projects = projectsResponse.projects || [];
      let project = projects[0];
      
      if (!project) {
        project = await api.projects.uploadManual('Licitação - Caixas e Reservatórios', 'Projeto demonstrativo', 11);
      }
      
      setProjectId(project.id);
      
      const response = await fetch(`${API_URL}/api/products/project/${project.id}`, {
        headers: { 'Content-Type': 'application/json' }
      });

      if (!response.ok) {
        throw new Error('Erro ao carregar produtos do projeto');
      }

      const products: Product[] = await response.json();
      
      const mappedItems: Item[] = products.map((product, index) => ({
        id: product.id,
        item_number: Number.parseInt(product.numero_lote || '', 10) || index + 1,
        name: product.name,
        description: product.description || product.name,
        quantity: product.quantity || 1,
        unit_price_max: product.valor_unitario_estimado || product.min_price || 0,
        total_price_max: product.valor_total_estimado || 0,
        status: mapProductStatus(product.status),
        offers: [],
        market_price: product.min_price || undefined,
      }));
      
      setItems(mappedItems);
      if (mappedItems.length > 0) {
        setSelectedItem(mappedItems[0]);
        setCmv(mappedItems[0].market_price || mappedItems[0].unit_price_max || 0);
      }
    } catch (error: unknown) {
      console.error('Erro ao carregar itens:', error);
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  const handleSearchPrices = async (itemId: string) => {
    setSearching(true);
    try {
      const result = await api.offers.search(itemId);
      
      setItems(prev => prev.map(item => {
        if (item.id === itemId) {
          return {
            ...item,
            offers: result.offers || [],
            market_price: result.menor_preco,
            recommended_price: result.menor_preco ? result.menor_preco * 1.15 : undefined, // +15% margem
          };
        }
        return item;
      }));
      
      if (selectedItem?.id === itemId) {
        const updatedItem = {
          ...selectedItem,
          offers: result.offers || [],
          market_price: result.menor_preco,
          recommended_price: result.menor_preco ? result.menor_preco * 1.15 : undefined,
        };
        setSelectedItem(updatedItem);
        if (result.menor_preco) {
          setCmv(result.menor_preco);
        }
      }
    } catch (error) {
      console.error('Erro na busca:', error);
    } finally {
      setSearching(false);
    }
  };

  const handleSearchAll = async () => {
    setSearching(true);
    try {
      // Buscar todos os preços do projeto
      await api.offers.searchAll(projectId, true);
      
      // Recarregar itens
      await loadItems();
    } catch (error) {
      console.error('Erro na busca geral:', error);
    } finally {
      setSearching(false);
    }
  };

  const calculateRecommendedPrice = () => {
    if (!selectedItem) return 0;
    const basePrice = cmv || (selectedItem.market_price || selectedItem.unit_price_max || 0);
    return basePrice * (1 + margin / 100);
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'APPROVED':
      case 'SUCCESS':
        return 'bg-emerald-500/20 text-emerald-400';
      case 'REJECTED':
      case 'DISCARDED':
      case 'ERROR':
      case 'ERROR_NOT_FOUND':
        return 'bg-red-500/20 text-red-400';
      case 'ANALYZING':
        return 'bg-amber-500/20 text-amber-400';
      default:
        return 'bg-zinc-500/20 text-zinc-400';
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'APPROVED':
      case 'SUCCESS':
        return 'Ganhando';
      case 'REJECTED':
      case 'DISCARDED':
        return 'Perdendo';
      case 'ERROR':
      case 'ERROR_NOT_FOUND':
        return 'Erro';
      case 'ANALYZING':
        return 'Analisando';
      default:
        return 'Pendente';
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center">
        <div className="text-violet-400 text-xl font-bold">Carregando Obsidian Procurement...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center">
        <div className="text-red-400 text-center">
          <p className="text-xl font-bold mb-2">Erro ao carregar</p>
          <p className="text-zinc-400">{error}</p>
          <button 
            onClick={loadItems}
            className="mt-4 px-6 py-2 bg-violet-600 text-white rounded-lg font-bold hover:bg-violet-700"
          >
            Tentar novamente
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#09090b] text-zinc-100 flex flex-col">
      {/* TopNavBar */}
      <header className="flex justify-between items-center px-4 h-16 w-full fixed top-0 bg-[#09090b] border-b border-[#27272a] z-50">
        <div className="flex items-center gap-8">
          <span className="text-lg font-black tracking-tighter text-[#fafafa]">Obsidian Procurement</span>
          <nav className="hidden md:flex items-center gap-6">
            <a href="/dashboard" className="text-[#a1a1aa] hover:bg-[#18181b] hover:text-[#fafafa] transition-colors px-2 py-1 rounded">Dashboard</a>
            <a href="/obsidian" className="text-[#a78bfa] font-bold border-b-2 border-[#a78bfa] pb-1">Lote Analysis</a>
            <a href="#" className="text-[#a1a1aa] hover:bg-[#18181b] hover:text-[#fafafa] transition-colors px-2 py-1 rounded">Market Insights</a>
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <button 
            onClick={handleSearchAll}
            disabled={searching}
            className="flex items-center gap-2 px-4 py-1.5 bg-violet-500 hover:bg-violet-600 text-white rounded-lg text-sm font-bold transition-colors disabled:opacity-50"
          >
            {searching ? 'Buscando...' : 'Run Analysis'}
          </button>
        </div>
      </header>

      {/* SideNavBar */}
      <aside className="fixed left-0 top-16 h-[calc(100vh-64px)] w-64 border-r border-[#27272a] bg-[#0c0c0f] flex flex-col pt-4 pb-8 hidden md:flex">
        <div className="px-6 mb-8">
          <h2 className="font-bold text-[#fafafa] tracking-tight">Pricing Engine</h2>
          <p className="text-[10px] text-zinc-400 tracking-widest uppercase">V2.4.0-Stable</p>
        </div>
        <nav className="flex-1 space-y-1">
          <a href="/dashboard" className="text-[#a1a1aa] px-4 py-3 flex items-center gap-3 hover:bg-[#18181b] hover:text-[#fafafa] transition-all cursor-pointer">
            <span>📊</span>
            <span className="text-sm">Dashboard</span>
          </a>
          <div className="bg-[#27272a] text-[#fafafa] border-l-4 border-[#a78bfa] px-4 py-3 flex items-center gap-3 cursor-pointer">
            <span>📈</span>
            <span className="text-sm font-bold">Lote Analysis</span>
          </div>
          <a href="#" className="text-[#a1a1aa] px-4 py-3 flex items-center gap-3 hover:bg-[#18181b] hover:text-[#fafafa] transition-all cursor-pointer">
            <span>🔍</span>
            <span className="text-sm">Market Insights</span>
          </a>
        </nav>
      </aside>

      {/* Main Content */}
      <main className="md:pl-64 pt-16 h-screen flex overflow-hidden">
        {/* Left Panel: Item List */}
        <section className="w-full md:w-[400px] border-r border-zinc-800 flex flex-col bg-[#0f0f12] shrink-0 overflow-hidden">
          {/* Header */}
          <div className="p-4 bg-[#121215] border-b border-zinc-800">
            <div className="flex justify-between items-center mb-2">
              <span className="text-xs font-bold text-violet-400 tracking-widest uppercase">LOTE 12</span>
              <span className="bg-emerald-500/10 text-emerald-400 text-[10px] px-2 py-0.5 rounded border border-emerald-500/20">
                {Math.round((items.filter(i => i.status === 'APPROVED' || i.status === 'SUCCESS').length / items.length) * 100) || 0}% PROGRESS
              </span>
            </div>
            <h3 className="text-lg font-bold tracking-tight">Caixas e Reservatórios</h3>
            <p className="text-xs text-zinc-400 mt-1">{items.length} itens para análise</p>
          </div>

          {/* List */}
          <div className="flex-1 overflow-y-auto">
            {items.map((item) => (
              <div 
                key={item.id}
                onClick={() => {
                  setSelectedItem(item);
                  setCmv(item.market_price || item.unit_price_max || 0);
                }}
                className={`p-4 border-b border-zinc-800 cursor-pointer transition-colors ${
                  selectedItem?.id === item.id 
                    ? 'bg-zinc-800/50 border-l-4 border-l-violet-500' 
                    : 'hover:bg-zinc-800/30'
                }`}
              >
                <div className="flex gap-3">
                  <input 
                    type="checkbox" 
                    checked={item.status === 'APPROVED' || item.status === 'SUCCESS'}
                    readOnly
                    className="mt-1 rounded border-zinc-700 bg-zinc-900 text-violet-500"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-start mb-1">
                      <span className="text-xs font-bold truncate">{item.name}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-bold uppercase ${getStatusColor(item.status)}`}>
                        {getStatusLabel(item.status)}
                      </span>
                    </div>
                    <p className="text-xs text-zinc-500 line-clamp-2">{item.description}</p>
                    <div className="mt-3 flex justify-between items-center">
                      <span className="text-sm font-bold">
                        R$ {(item.market_price || item.unit_price_max || 0).toFixed(2)}
                      </span>
                      <span className="text-[10px] text-zinc-500">Qtd: {item.quantity} un</span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Right Panel: Detail */}
        <section className="flex-1 overflow-y-auto bg-[#09090b] p-6 lg:p-10">
          {selectedItem ? (
            <div className="max-w-5xl mx-auto space-y-10">
              {/* Header */}
              <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
                <div>
                  <div className="flex items-center gap-2 text-violet-400 mb-2">
                    <span>📦</span>
                    <span className="text-xs font-bold uppercase tracking-widest">Item #{selectedItem.item_number}</span>
                  </div>
                  <h1 className="text-3xl font-black tracking-tight">{selectedItem.name}</h1>
                  <p className="text-zinc-400 mt-2 max-w-2xl">{selectedItem.description}</p>
                </div>
                <button 
                  onClick={() => handleSearchPrices(selectedItem.id)}
                  disabled={searching}
                  className="px-6 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg font-bold transition-colors disabled:opacity-50"
                >
                  {searching ? 'Buscando...' : 'Buscar Preços'}
                </button>
              </div>

              {/* Grid */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                {/* Dados do Edital */}
                <div className="lg:col-span-7 bg-[#121215] border border-zinc-800 rounded-xl p-6">
                  <div className="flex items-center gap-2 mb-6">
                    <span className="text-violet-400">📝</span>
                    <h2 className="font-bold tracking-tight">Dados do Edital</h2>
                  </div>
                  <div className="space-y-4">
                    <div className="p-4 bg-[#0f0f12] rounded-lg border border-zinc-800/50">
                      <p className="text-[10px] text-violet-400 uppercase font-bold tracking-wider mb-2">Descrição do PDF</p>
                      <p className="text-sm leading-relaxed text-zinc-400 italic">{selectedItem.description}</p>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="p-4 bg-[#0f0f12] rounded-lg border border-zinc-800/50">
                        <p className="text-[10px] text-zinc-500 uppercase font-bold tracking-wider mb-1">Quantidade</p>
                        <p className="text-xl font-bold">{selectedItem.quantity} <span className="text-sm font-normal text-zinc-500">un</span></p>
                      </div>
                      <div className="p-4 bg-[#0f0f12] rounded-lg border border-zinc-800/50">
                        <p className="text-[10px] text-zinc-500 uppercase font-bold tracking-wider mb-1">Preço de Referência</p>
                        <p className="text-xl font-bold text-emerald-400">R$ {(selectedItem.unit_price_max || 0).toFixed(2)}</p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Market Benchmarking */}
                <div className="lg:col-span-5 bg-[#121215] border border-zinc-800 rounded-xl p-6">
                  <div className="flex items-center gap-2 mb-6">
                    <span className="text-violet-400">📊</span>
                    <h2 className="font-bold tracking-tight">Market Benchmarking</h2>
                  </div>
                  <div className="space-y-3">
                    {selectedItem.offers.length > 0 ? (
                      selectedItem.offers.slice(0, 4).map((offer, idx) => (
                        <div key={idx} className="flex items-center justify-between p-3 border-b border-zinc-800">
                          <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded bg-zinc-700 flex items-center justify-center text-xs">
                              {offer.marketplace?.[0] || 'M'}
                            </div>
                            <div>
                              <span className="text-sm font-medium block">{offer.marketplace}</span>
                              {offer.is_best_seller && (
                                <span className="text-[10px] text-amber-400">⭐ Mais Vendido</span>
                              )}
                            </div>
                          </div>
                          <span className="text-sm font-bold">R$ {offer.price.toFixed(2)}</span>
                        </div>
                      ))
                    ) : (
                      <div className="text-center py-8 text-zinc-500">
                        <p>Nenhuma oferta encontrada</p>
                        <p className="text-sm mt-2">Clique em &quot;Buscar Preços&quot; para analisar</p>
                      </div>
                    )}
                    
                    {selectedItem.market_price && (
                      <div className="mt-4 pt-4 bg-violet-500/5 rounded-lg p-3 border border-violet-500/20">
                        <div className="flex justify-between items-center">
                          <span className="text-xs text-zinc-400 font-medium">Menor Preço Encontrado</span>
                          <span className="text-lg font-black text-violet-400">
                            R$ {selectedItem.market_price.toFixed(2)}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Calculadora de Margem */}
                <div className="lg:col-span-12 bg-[#121215] border border-zinc-800 rounded-xl p-8">
                  <div className="flex items-center gap-2 mb-6">
                    <span className="text-violet-400">🧮</span>
                    <h2 className="font-bold tracking-tight">Calculadora de Margem Inteligente</h2>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-4">
                      <div>
                        <label className="block text-xs font-bold text-zinc-400 mb-2 uppercase tracking-widest">
                          Custo da Unidade (CMV)
                        </label>
                        <div className="relative">
                          <span className="absolute left-4 top-1/2 -translate-y-1/2 text-zinc-500 text-sm">R$</span>
                          <input 
                            type="number" 
                            value={cmv}
                            onChange={(e) => setCmv(parseFloat(e.target.value) || 0)}
                            className="w-full bg-[#0f0f12] border border-zinc-700 rounded-lg pl-10 pr-4 py-3 text-lg font-bold focus:ring-2 focus:ring-violet-500 focus:outline-none"
                          />
                        </div>
                      </div>
                      <div>
                        <label className="block text-xs font-bold text-zinc-400 mb-2 uppercase tracking-widest">
                          Margem de Lucro Desejada (%)
                        </label>
                        <div className="flex items-center gap-4">
                          <input 
                            type="range" 
                            min="5" 
                            max="50" 
                            value={margin}
                            onChange={(e) => setMargin(parseInt(e.target.value))}
                            className="flex-1 h-2 bg-zinc-700 rounded-lg accent-violet-500"
                          />
                          <span className="text-xl font-bold w-12 text-center">{margin}%</span>
                        </div>
                      </div>
                    </div>
                    <div className="bg-[#1e1e22] rounded-xl p-6 border border-zinc-800 flex flex-col justify-center">
                      <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest mb-2 text-center">
                        Preço de Venda Recomendado
                      </p>
                      <div className="text-center">
                        <span className="text-5xl font-black tracking-tighter text-white">
                          R$ {calculateRecommendedPrice().toFixed(2)}
                        </span>
                        {(selectedItem.unit_price_max || 0) > 0 && (
                          <div className="mt-4 flex items-center justify-center gap-2">
                            {calculateRecommendedPrice() < selectedItem.unit_price_max ? (
                              <>
                                <span className="text-emerald-400 text-sm">✓</span>
                                <span className="text-xs text-emerald-400 font-bold">
                                  {((1 - calculateRecommendedPrice() / selectedItem.unit_price_max) * 100).toFixed(1)}% ABAIXO DO EDITAL
                                </span>
                              </>
                            ) : (
                              <>
                                <span className="text-red-400 text-sm">⚠</span>
                                <span className="text-xs text-red-400 font-bold">
                                  ACIMA DO PREÇO MÁXIMO
                                </span>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="lg:col-span-12 flex justify-end gap-4 pb-12">
                  <button 
                    onClick={async () => {
                      await api.products.updateStatus(selectedItem.id, 'DISCARDED');
                      loadItems();
                    }}
                    className="px-10 py-4 border-2 border-zinc-700 rounded-xl text-white font-bold hover:bg-red-900/30 hover:border-red-500 transition-all flex items-center gap-2"
                  >
                    <span>✕</span> Rejeitar
                  </button>
                  <button 
                    onClick={async () => {
                      await api.products.updateStatus(selectedItem.id, 'APPROVED');
                      loadItems();
                    }}
                    className="px-12 py-4 bg-violet-600 text-white rounded-xl text-lg font-black hover:bg-violet-700 transition-all flex items-center gap-3"
                  >
                    <span>✓</span> Aprovar Preço
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-zinc-500">
              <p>Selecione um item para analisar</p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
