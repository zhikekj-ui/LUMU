"""Data visualization — generate charts from data using Matplotlib and Plotly."""
import base64
import io
import json
import os
from pathlib import Path
from typing import Optional


class ChartGenerator:
    """Generate charts from data using Matplotlib (static) and Plotly (interactive)."""

    SUPPORTED_CHARTS = [
        "line", "bar", "barh", "scatter", "pie", "hist",
        "box", "heatmap", "area", "radar", "violin",
    ]

    # Chinese font configuration
    CHINESE_FONTS = [
        "WenQuanYi Zen Hei",
        "WenQuanYi Micro Hei",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "SimHei",
        "Microsoft YaHei",
        "STHeiti",
        "sans-serif",
    ]

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._setup_matplotlib()

    def _setup_matplotlib(self):
        """Configure Matplotlib for Chinese text support."""
        try:
            import matplotlib
            matplotlib.use("Agg")  # Non-interactive backend
            import matplotlib.pyplot as plt
            import matplotlib.font_manager as fm

            # Only pick a font that is ACTUALLY installed on this system.
            # (The previous loop set the first name blindly, so a non-existent
            #  font like "WenQuanYi Micro Hei" slipped through and Chinese
            #  text fell back to tofu boxes.)
            available = {f.name for f in fm.fontManager.ttflist}
            chosen = None
            for font in self.CHINESE_FONTS:
                if font == "sans-serif" or font in available:
                    chosen = font
                    break
            if chosen:
                plt.rcParams["font.sans-serif"] = [chosen] + [
                    f for f in plt.rcParams["font.sans-serif"] if f != chosen
                ]
            plt.rcParams["axes.unicode_minus"] = False  # Fix minus sign display
            self.plt = plt
            self.matplotlib_available = True
            self.chinese_font = chosen
        except ImportError:
            self.matplotlib_available = False

    def generate(self, chart_type: str, data: dict, title: str = "",
                 xlabel: str = "", ylabel: str = "", figsize: tuple = (10, 6),
                 filename: str = None, format: str = "png", dpi: int = 150) -> dict:
        """Generate a chart from data.
        
        Args:
            chart_type: One of line, bar, barh, scatter, pie, hist, box, heatmap, area
            data: Dict with 'x' and 'y' keys (or 'labels'/'values' for pie)
            title: Chart title
            xlabel: X-axis label
            ylabel: Y-axis label
            figsize: Figure size as (width, height)
            filename: Output filename (auto-generated if None)
            format: Output format (png, svg, pdf)
            dpi: Resolution for raster formats
        
        Returns:
            Dict with file path, base64 image, and metadata
        """
        if not self.matplotlib_available:
            return {"success": False, "error": "Matplotlib not installed"}

        if chart_type not in self.SUPPORTED_CHARTS:
            return {"success": False, "error": f"Unsupported chart type: {chart_type}"}

        try:
            fig, ax = self.plt.subplots(figsize=figsize)
            
            # Generate chart based on type
            if chart_type == "line":
                self._line_chart(ax, data)
            elif chart_type == "bar":
                self._bar_chart(ax, data)
            elif chart_type == "barh":
                self._barh_chart(ax, data)
            elif chart_type == "scatter":
                self._scatter_chart(ax, data)
            elif chart_type == "pie":
                self._pie_chart(ax, data)
            elif chart_type == "hist":
                self._hist_chart(ax, data)
            elif chart_type == "box":
                self._box_chart(ax, data)
            elif chart_type == "heatmap":
                self._heatmap_chart(ax, data)
            elif chart_type == "area":
                self._area_chart(ax, data)

            # Set labels and title
            if title:
                self.plt.title(title, fontsize=14, fontweight="bold", pad=15)
            if xlabel:
                self.plt.xlabel(xlabel, fontsize=11)
            if ylabel:
                self.plt.ylabel(ylabel, fontsize=11)

            # Adjust layout
            self.plt.tight_layout()

            # Save to file
            if not filename:
                filename = f"chart_{chart_type}_{id(data)}.{format}"
            
            filepath = self.output_dir / filename
            fig.savefig(str(filepath), format=format, dpi=dpi, bbox_inches="tight",
                       facecolor="white", edgecolor="none")
            self.plt.close(fig)

            # Generate base64 for inline display
            buf = io.BytesIO()
            fig.savefig(buf, format=format, dpi=dpi, bbox_inches="tight",
                       facecolor="white", edgecolor="none")
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode("utf-8")

            return {
                "success": True,
                "filepath": str(filepath),
                "filename": filename,
                "base64": img_base64,
                "format": format,
                "chart_type": chart_type,
            }

        except Exception as e:
            self.plt.close("all")
            return {"success": False, "error": str(e)}

    def _line_chart(self, ax, data: dict):
        """Line chart."""
        x = data.get("x", [])
        y_data = data.get("y", [])
        
        if isinstance(y_data[0], (list, tuple)):
            # Multiple series
            labels = data.get("labels", [f"Series {i+1}" for i in range(len(y_data))])
            for i, y in enumerate(y_data):
                ax.plot(x, y, marker="o", markersize=4, label=labels[i], linewidth=2)
            ax.legend()
        else:
            ax.plot(x, y_data, marker="o", markersize=4, linewidth=2, color="#4C78A8")
        
        ax.grid(True, alpha=0.3)

    def _bar_chart(self, ax, data: dict):
        """Vertical bar chart."""
        x = data.get("x", [])
        y = data.get("y", [])
        colors = data.get("colors", ["#4C78A8", "#F58518", "#E45756", "#72B7B2", "#54A24B"])
        
        if isinstance(y[0], (list, tuple)):
            # Grouped bars
            import numpy as np
            n_groups = len(x)
            n_series = len(y)
            bar_width = 0.8 / n_series
            indices = np.arange(n_groups)
            
            for i, series in enumerate(y):
                offset = (i - n_series / 2 + 0.5) * bar_width
                ax.bar(indices + offset, series, bar_width, label=data.get("labels", [f"S{i+1}"])[i],
                      color=colors[i % len(colors)])
            ax.legend()
        else:
            bar_colors = [colors[i % len(colors)] for i in range(len(x))]
            ax.bar(x, y, color=bar_colors)
        
        ax.grid(True, axis="y", alpha=0.3)

    def _barh_chart(self, ax, data: dict):
        """Horizontal bar chart."""
        y = data.get("y", data.get("x", []))
        x = data.get("x", data.get("y", []))
        colors = data.get("colors", ["#4C78A8"])
        
        bar_colors = [colors[i % len(colors)] for i in range(len(y))]
        ax.barh(y, x, color=bar_colors)
        ax.grid(True, axis="x", alpha=0.3)

    def _scatter_chart(self, ax, data: dict):
        """Scatter plot."""
        x = data.get("x", [])
        y = data.get("y", [])
        
        if isinstance(y[0], (list, tuple)):
            labels = data.get("labels", [f"Group {i+1}" for i in range(len(y))])
            for i, (xi, yi) in enumerate(zip(x, y)):
                ax.scatter(xi, yi, label=labels[i], alpha=0.7, s=50)
            ax.legend()
        else:
            ax.scatter(x, y, alpha=0.7, s=50, color="#4C78A8")
        
        ax.grid(True, alpha=0.3)

    def _pie_chart(self, ax, data: dict):
        """Pie chart."""
        labels = data.get("labels", data.get("x", []))
        values = data.get("values", data.get("y", []))
        colors = data.get("colors", ["#4C78A8", "#F58518", "#E45756", "#72B7B2", "#54A24B", "#FF9DA6"])
        
        wedges, texts, autotexts = ax.pie(
            values, labels=labels, colors=colors[:len(values)],
            autopct="%1.1f%%", startangle=90, pctdistance=0.85,
        )
        for autotext in autotexts:
            autotext.set_fontsize(9)
        ax.axis("equal")

    def _hist_chart(self, ax, data: dict):
        """Histogram."""
        values = data.get("values", data.get("y", data.get("x", [])))
        bins = data.get("bins", 20)
        
        if isinstance(values[0], (list, tuple)):
            labels = data.get("labels", [f"Series {i+1}" for i in range(len(values))])
            for i, v in enumerate(values):
                ax.hist(v, bins=bins, alpha=0.6, label=labels[i])
            ax.legend()
        else:
            ax.hist(values, bins=bins, color="#4C78A8", alpha=0.8, edgecolor="white")
        
        ax.grid(True, axis="y", alpha=0.3)

    def _box_chart(self, ax, data: dict):
        """Box plot."""
        values = data.get("values", data.get("y", []))
        labels = data.get("labels", None)
        
        bp = ax.boxplot(values, labels=labels, patch_artist=True)
        
        colors = ["#4C78A8", "#F58518", "#E45756", "#72B7B2", "#54A24B"]
        for patch, color in zip(bp["boxes"], colors * 10):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        
        ax.grid(True, axis="y", alpha=0.3)

    def _heatmap_chart(self, ax, data: dict):
        """Heatmap."""
        import numpy as np
        
        values = data.get("values", data.get("z", []))
        x_labels = data.get("x", [])
        y_labels = data.get("y", [])
        
        if isinstance(values, list) and isinstance(values[0], list):
            values = np.array(values)
        else:
            values = np.array(values).reshape(-1, 1)
        
        im = ax.imshow(values, cmap="YlOrRd", aspect="auto")
        
        if x_labels:
            ax.set_xticks(range(len(x_labels)))
            ax.set_xticklabels(x_labels, rotation=45, ha="right")
        if y_labels:
            ax.set_yticks(range(len(y_labels)))
            ax.set_yticklabels(y_labels)
        
        self.plt.colorbar(im, ax=ax, shrink=0.8)

    def _area_chart(self, ax, data: dict):
        """Area chart (stacked)."""
        x = data.get("x", [])
        y_data = data.get("y", [])
        
        if isinstance(y_data[0], (list, tuple)):
            labels = data.get("labels", [f"Series {i+1}" for i in range(len(y_data))])
            ax.stackplot(x, y_data, labels=labels, alpha=0.7)
            ax.legend(loc="upper left")
        else:
            ax.fill_between(x, y_data, alpha=0.7, color="#4C78A8")
        
        ax.grid(True, alpha=0.3)

    def generate_from_dataframe(self, df_data: dict, chart_type: str = "bar",
                                x_col: str = None, y_col: str = None,
                                title: str = "", **kwargs) -> dict:
        """Generate chart from DataFrame-like dict.
        
        Args:
            df_data: Dict of lists (column-oriented), e.g. {"name": ["A","B"], "value": [1,2]}
            chart_type: Chart type
            x_col: Column name for x-axis
            y_col: Column name for y-axis
            title: Chart title
        """
        columns = list(df_data.keys())
        if not columns:
            return {"success": False, "error": "Empty data"}

        if x_col and y_col:
            data = {"x": df_data[x_col], "y": df_data[y_col]}
        else:
            # Auto-detect: first column as x, rest as y
            x_col = columns[0]
            y_cols = columns[1:] if len(columns) > 1 else columns
            data = {
                "x": df_data[x_col],
                "y": [df_data[c] for c in y_cols],
                "labels": y_cols,
            }

        return self.generate(chart_type, data, title=title, 
                           xlabel=x_col or "", ylabel=y_col or "", **kwargs)

    def list_chart_types(self) -> list[str]:
        """List supported chart types."""
        return self.SUPPORTED_CHARTS
