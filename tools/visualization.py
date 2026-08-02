"""Visualization tools — generate charts from data for the agent."""
import os
from pathlib import Path
from tools.registry import ToolRegistry


def _get_chart_generator():
    """Lazy-init chart generator."""
    from visualization.charts import ChartGenerator
    output_dir = os.path.join(os.getenv("AGENT_HOME", str(Path(__file__).resolve().parent.parent)), "data", "charts")
    return ChartGenerator(output_dir=output_dir)


def handle_generate_chart(**kwargs):
    """Generate a chart from data.
    
    Args:
        chart_type: Chart type (line, bar, barh, scatter, pie, hist, box, heatmap, area)
        data: JSON data with 'x' and 'y' keys (or 'labels'/'values' for pie)
        title: Chart title
        xlabel: X-axis label
        ylabel: Y-axis label
        filename: Output filename (auto-generated if not specified)
    """
    import json
    
    chart_type = kwargs.get("chart_type", "bar")
    data = kwargs.get("data", {})
    title = kwargs.get("title", "")
    xlabel = kwargs.get("xlabel", "")
    ylabel = kwargs.get("ylabel", "")
    filename = kwargs.get("filename", "")
    
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return {"error": "Invalid JSON data"}
    
    if not data:
        return {"error": "Data is empty"}
    
    try:
        generator = _get_chart_generator()
        result = generator.generate(
            chart_type=chart_type,
            data=data,
            title=title,
            xlabel=xlabel,
            ylabel=ylabel,
            filename=filename if filename else None,
        )
        # Remove base64 from response to keep it small
        if result.get("success"):
            result.pop("base64", None)
        return result
    except Exception as e:
        return {"error": str(e)}


def handle_generate_chart_from_data(**kwargs):
    """Generate a chart from column-oriented data (like a DataFrame).
    
    Args:
        data: Column-oriented dict, e.g. {"name": ["A","B"], "value": [10,20]}
        chart_type: Chart type
        x_col: Column name for x-axis
        y_col: Column name for y-axis
        title: Chart title
    """
    import json
    
    data = kwargs.get("data", {})
    chart_type = kwargs.get("chart_type", "bar")
    x_col = kwargs.get("x_col", "")
    y_col = kwargs.get("y_col", "")
    title = kwargs.get("title", "")
    
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return {"error": "Invalid JSON data"}
    
    if not data:
        return {"error": "Data is empty"}
    
    try:
        generator = _get_chart_generator()
        result = generator.generate_from_dataframe(
            df_data=data,
            chart_type=chart_type,
            x_col=x_col if x_col else None,
            y_col=y_col if y_col else None,
            title=title,
        )
        if result.get("success"):
            result.pop("base64", None)
        return result
    except Exception as e:
        return {"error": str(e)}


def handle_list_chart_types(**kwargs):
    """List all supported chart types."""
    try:
        generator = _get_chart_generator()
        return {"chart_types": generator.list_chart_types()}
    except Exception as e:
        return {"error": str(e)}


def register(registry: ToolRegistry):
    """Register visualization tools."""
    registry.register(
        name="generate_chart",
        description="从数据生成图表。支持折线图(line)、柱状图(bar)、水平柱状图(barh)、散点图(scatter)、饼图(pie)、直方图(hist)、箱线图(box)、热力图(heatmap)、面积图(area)。返回图片文件路径。",
        handler=handle_generate_chart,
        toolset="visualization",
        parameters={
            "chart_type": {"type": "string", "description": "图表类型", "required": True},
            "data": {"type": "string", "description": "JSON数据，含x和y键", "required": True},
            "title": {"type": "string", "description": "图表标题", "required": False},
            "xlabel": {"type": "string", "description": "X轴标签", "required": False},
            "ylabel": {"type": "string", "description": "Y轴标签", "required": False},
            "filename": {"type": "string", "description": "输出文件名", "required": False},
        },
    )
    
    registry.register(
        name="generate_chart_from_data",
        description="从列式数据（类似DataFrame格式）生成图表。自动检测x/y列。",
        handler=handle_generate_chart_from_data,
        toolset="visualization",
        parameters={
            "data": {"type": "string", "description": "列式JSON数据，如{\"name\":[\"A\",\"B\"],\"value\":[10,20]}", "required": True},
            "chart_type": {"type": "string", "description": "图表类型", "required": False},
            "x_col": {"type": "string", "description": "X轴列名", "required": False},
            "y_col": {"type": "string", "description": "Y轴列名", "required": False},
            "title": {"type": "string", "description": "图表标题", "required": False},
        },
    )
    
    registry.register(
        name="list_chart_types",
        description="列出所有支持的图表类型。",
        handler=handle_list_chart_types,
        toolset="visualization",
        parameters={},
    )
