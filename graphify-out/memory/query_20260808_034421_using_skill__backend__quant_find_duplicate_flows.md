---
type: "query"
date: "2026-08-08T03:44:21.422777+00:00"
question: "using skill /backend /quant find duplicate flows"
contributor: "graphify"
source_nodes: ["amt_result_to_dto", "TradeThesis", "VWAPState", "VolumeProfile", "JournalEntry", "LiveGateway", "Position", "Fill", "gguf_inference_adapter"]
---

# Q: using skill /backend /quant find duplicate flows

## Answer

Expanded from original query via vocab: [backend, quant, flow, flows, duplicate, pipeline, service, adapter, analyzer, engine, detector, scorer]. Traversed graph.json comparing production (non-test) symbols defined in both backend/ and quant/. Found 1184 test-mirror duplicates (intentional parity tests) plus ~40 production symbols duplicated across both trees. Genuine duplicate FLOWS (independent reimplementations): amt_result_to_dto (schemas.py vs quant/amt/dto.py), TradeThesis, VWAPState/VolumeProfile (market_state.py vs quant/vwap.py+volume_profile.py), JournalEntry, LiveGateway, Position/Fill aggregate (trade_aggregate.py 770 lines vs quant/contracts/entities.py), gguf_inference_adapter parallel methods (_load_model/predict/is_ready/_extract_json_candidate/_start_background_loading) mirroring quant/inference/mlx_inference_adapter.py, _to_float helper, ExchangeConfig. Intentional port/adapter pairs (NOT duplication): storage database.py implements quant IStorage port, dhan/paper broker adapters implement broker port, live_gateway implements gateway port, lgbm adapter implements probability port.

## Source Nodes

- amt_result_to_dto
- TradeThesis
- VWAPState
- VolumeProfile
- JournalEntry
- LiveGateway
- Position
- Fill
- gguf_inference_adapter