#!/bin/bash
# Deployment script for LUMU AI agent framework enhancements
# Deploys: multi-provider, RAG, code sandbox, TTS/STT, visualization, knowledge base

set -e

echo "=== LUMU AI Agent Framework - Enhancement Deployment ==="
echo "Deploying: Multi-Provider, RAG, Code Sandbox, TTS/STT, Visualization, Knowledge Base"
echo ""

# Create tarball
echo "[1/6] Creating deployment package..."
cd /Users/dakuang/.qoderworkcn/workspace/fd04e770-3c3d-4211-9a55-898e3cc9fe5e/agent-update
tar --exclude='._*' -czf /tmp/agent-enhancements.tar.gz .
echo "Package created: /tmp/agent-enhancements.tar.gz"
echo ""

# Upload to server
echo "[2/6] Uploading to server..."
scp /tmp/agent-enhancements.tar.gz root@154.12.86.137:/tmp/
echo "Upload complete"
echo ""

# Extract and deploy on server
echo "[3/6] Extracting on server..."
ssh root@154.12.86.137 << 'ENDSSH'
cd /opt/agent-framework

# Backup current state
echo "Creating backup..."
cp -r tools tools.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true

# Extract new files
echo "Extracting deployment package..."
cd /tmp
tar -xzf agent-enhancements.tar.gz -C /opt/agent-framework/

# Clean up macOS resource forks
find /opt/agent-framework -name '._*' -delete

# Set permissions
chown -R root:root /opt/agent-framework/rag /opt/agent-framework/sandbox /opt/agent-framework/visualization /opt/agent-framework/knowledge
chown -R root:root /opt/agent-framework/plugins/model-providers/glm_provider.py
chown -R root:root /opt/agent-framework/plugins/model-providers/qwen_provider.py
chown -R root:root /opt/agent-framework/plugins/model-providers/moonshot_provider.py
chown -R root:root /opt/agent-framework/tools/multi_provider.py
chown -R root:root /opt/agent-framework/tools/rag_tool.py
chown -R root:root /opt/agent-framework/tools/code_sandbox.py
chown -R root:root /opt/agent-framework/tools/visualization.py
chown -R root:root /opt/agent-framework/tools/knowledge.py
chown -R root:root /opt/agent-framework/tools/tts_stt.py

echo "Extraction complete"
ENDSSH

echo ""
echo "[4/6] Installing Python dependencies..."
ssh root@154.12.86.137 << 'ENDSSH'
cd /opt/agent-framework

# Install core dependencies
echo "Installing document parsing libraries..."
.venv/bin/pip install --quiet PyPDF2 python-docx openpyxl python-pptx

echo "Installing visualization libraries..."
.venv/bin/pip install --quiet matplotlib

echo "Installing TTS/STT dependencies..."
.venv/bin/pip install --quiet edge-tts

echo "Installing Docker SDK for sandbox..."
.venv/bin/pip install --quiet docker

echo "Installing requests for API calls..."
.venv/bin/pip install --quiet requests

echo "Dependencies installed"
ENDSSH

echo ""
echo "[5/6] Restarting agent service..."
ssh root@154.12.86.137 << 'ENDSSH'
systemctl restart agent-framework
sleep 3
systemctl status agent-framework --no-pager | head -15
ENDSSH

echo ""
echo "[6/6] Testing new features..."
ssh root@154.12.86.137 << 'ENDSSH'
cd /opt/agent-framework

# Test provider discovery
echo "Testing provider discovery..."
.venv/bin/python -c "
from providers.registry import discover_providers, list_providers
discover_providers()
providers = list_providers()
print(f'✓ Discovered {len(providers)} providers:')
for p in providers:
    print(f'  - {p.display_name} ({p.name})')
"

# Test tool discovery
echo ""
echo "Testing tool discovery..."
.venv/bin/python -c "
from tools.registry import ToolRegistry
registry = ToolRegistry()
registry.discover()
tools = registry.list_tools()
print(f'✓ Discovered {len(tools)} tools')

# Check for new tools
new_tools = ['list_providers', 'rag_ingest_file', 'run_python', 'generate_chart', 'kb_add', 'tts_synthesize']
found = [t for t in new_tools if t in tools]
print(f'✓ New tools registered: {len(found)}/{len(new_tools)}')
for t in found:
    print(f'  - {t}')
"

# Test RAG module
echo ""
echo "Testing RAG module..."
.venv/bin/python -c "
from rag.pipeline import RAGPipeline
import tempfile, os
with tempfile.TemporaryDirectory() as tmpdir:
    pipeline = RAGPipeline(data_dir=tmpdir)
    result = pipeline.ingest_text('LUMU AI是一个智能体框架，支持多种功能。', collection='test')
    print(f'✓ RAG ingest: {result}')
    query_result = pipeline.query('智能体框架', collection='test')
    print(f'✓ RAG query: found {query_result[\"num_results\"]} results')
"

# Test knowledge base
echo ""
echo "Testing knowledge base..."
.venv/bin/python -c "
from knowledge.base import KnowledgeBase
import tempfile
with tempfile.TemporaryDirectory() as tmpdir:
    kb = KnowledgeBase(db_path=os.path.join(tmpdir, 'test.db'))
    result = kb.add(title='测试条目', content='这是测试内容', category='test')
    print(f'✓ KB add: {result}')
    search_result = kb.search('测试')
    print(f'✓ KB search: found {len(search_result)} results')
"

# Test visualization
echo ""
echo "Testing visualization..."
.venv/bin/python -c "
from visualization.charts import ChartGenerator
import tempfile
with tempfile.TemporaryDirectory() as tmpdir:
    gen = ChartGenerator(output_dir=tmpdir)
    result = gen.generate('bar', {'x': ['A', 'B', 'C'], 'y': [10, 20, 15]}, title='Test Chart')
    print(f'✓ Chart generation: {result[\"success\"]}')
"

echo ""
echo "=== Deployment Complete ==="
ENDSSH

echo ""
echo "Deployment finished successfully!"
echo "New capabilities:"
echo "  - 6 LLM Providers (StepFun, DeepSeek, GLM, Qwen, Moonshot, OpenAI)"
echo "  - RAG document parsing (PDF, Word, Excel, PPT, TXT, MD, CSV, HTML)"
echo "  - Code execution sandbox (Python, JavaScript with Docker isolation)"
echo "  - TTS/STT (MiMo TTS, Edge TTS, Whisper STT)"
echo "  - Data visualization (9 chart types with Matplotlib)"
echo "  - Knowledge base (persistent storage with hybrid search)"
