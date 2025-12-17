#!/usr/bin/env python3
"""
Advanced Data Visualization and Analytics Engine
Comprehensive toolkit for creating interactive visualizations, statistical analysis,
and data-driven insights with support for multiple chart types and export formats.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, List, Any, Optional, Tuple, Union, Callable
from dataclasses import dataclass
import json
import io
import base64
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Set style for better-looking plots
plt.style.use('seaborn-v0_8')
sns.set_palette("husl")

@dataclass
class ChartConfig:
    """Configuration for chart styling and layout."""
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    figsize: Tuple[int, int] = (12, 8)
    dpi: int = 100
    style: str = "seaborn"
    color_palette: str = "husl"
    grid: bool = True
    legend: bool = True
    save_format: str = "png"
    transparent: bool = False

@dataclass
class StatisticalSummary:
    """Container for statistical analysis results."""
    mean: float
    median: float
    std: float
    min_val: float
    max_val: float
    q25: float
    q75: float
    skewness: float
    kurtosis: float
    count: int
    missing_values: int

class DataVisualizer:
    """Main class for data visualization and analysis."""
    
    def __init__(self, config: Optional[ChartConfig] = None):
        """Initialize the visualizer with optional configuration."""
        self.config = config or ChartConfig()
        self.figures = []
        self.data_cache = {}
        
    def load_data(self, data: Union[pd.DataFrame, Dict[str, List], str], 
                  name: str = "data") -> pd.DataFrame:
        """
        Load and cache data for visualization.
        
        Args:
            data: Input data (DataFrame, dict, or file path)
            name: Name to cache the data under
            
        Returns:
            Loaded DataFrame
        """
        if isinstance(data, str):
            # Load from file
            if data.endswith('.csv'):
                df = pd.read_csv(data)
            elif data.endswith('.json'):
                df = pd.read_json(data)
            elif data.endswith('.xlsx'):
                df = pd.read_excel(data)
            else:
                raise ValueError(f"Unsupported file format: {data}")
        elif isinstance(data, dict):
            df = pd.DataFrame(data)
        elif isinstance(data, pd.DataFrame):
            df = data.copy()
        else:
            raise ValueError("Data must be DataFrame, dict, or file path")
        
        self.data_cache[name] = df
        return df
    
    def create_line_plot(self, data: pd.DataFrame, x: str, y: Union[str, List[str]], 
                        config: Optional[ChartConfig] = None) -> plt.Figure:
        """
        Create a line plot.
        
        Args:
            data: DataFrame containing the data
            x: Column name for x-axis
            y: Column name(s) for y-axis
            config: Optional chart configuration
            
        Returns:
            Matplotlib figure object
        """
        config = config or self.config
        
        fig, ax = plt.subplots(figsize=config.figsize, dpi=config.dpi)
        
        if isinstance(y, str):
            y = [y]
        
        for col in y:
            ax.plot(data[x], data[col], label=col, linewidth=2, marker='o', markersize=4)
        
        ax.set_title(config.title, fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel(config.xlabel, fontsize=12)
        ax.set_ylabel(config.ylabel, fontsize=12)
        
        if config.grid:
            ax.grid(True, alpha=0.3)
        
        if config.legend and len(y) > 1:
            ax.legend(fontsize=10)
        
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        self.figures.append(fig)
        return fig
    
    def create_bar_plot(self, data: pd.DataFrame, x: str, y: str, 
                       config: Optional[ChartConfig] = None) -> plt.Figure:
        """
        Create a bar plot.
        
        Args:
            data: DataFrame containing the data
            x: Column name for x-axis (categorical)
            y: Column name for y-axis (numerical)
            config: Optional chart configuration
            
        Returns:
            Matplotlib figure object
        """
        config = config or self.config
        
        fig, ax = plt.subplots(figsize=config.figsize, dpi=config.dpi)
        
        bars = ax.bar(data[x], data[y], color=sns.color_palette(config.color_palette, len(data)))
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{height:.1f}', ha='center', va='bottom')
        
        ax.set_title(config.title, fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel(config.xlabel, fontsize=12)
        ax.set_ylabel(config.ylabel, fontsize=12)
        
        if config.grid:
            ax.grid(True, alpha=0.3, axis='y')
        
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        self.figures.append(fig)
        return fig
    
    def create_scatter_plot(self, data: pd.DataFrame, x: str, y: str, 
                           size: Optional[str] = None, color: Optional[str] = None,
                           config: Optional[ChartConfig] = None) -> plt.Figure:
        """
        Create a scatter plot.
        
        Args:
            data: DataFrame containing the data
            x: Column name for x-axis
            y: Column name for y-axis
            size: Optional column name for bubble sizes
            color: Optional column name for color mapping
            config: Optional chart configuration
            
        Returns:
            Matplotlib figure object
        """
        config = config or self.config
        
        fig, ax = plt.subplots(figsize=config.figsize, dpi=config.dpi)
        
        # Prepare scatter plot parameters
        scatter_kwargs = {'alpha': 0.7}
        
        if size:
            scatter_kwargs['s'] = data[size] * 10  # Scale for visibility
        
        if color:
            scatter = ax.scatter(data[x], data[y], c=data[color], 
                               cmap=config.color_palette, **scatter_kwargs)
            plt.colorbar(scatter, ax=ax, label=color)
        else:
            ax.scatter(data[x], data[y], **scatter_kwargs)
        
        ax.set_title(config.title, fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel(config.xlabel, fontsize=12)
        ax.set_ylabel(config.ylabel, fontsize=12)
        
        if config.grid:
            ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        self.figures.append(fig)
        return fig
    
    def create_histogram(self, data: pd.DataFrame, column: str, bins: int = 30,
                        config: Optional[ChartConfig] = None) -> plt.Figure:
        """
        Create a histogram.
        
        Args:
            data: DataFrame containing the data
            column: Column name to plot
            bins: Number of histogram bins
            config: Optional chart configuration
            
        Returns:
            Matplotlib figure object
        """
        config = config or self.config
        
        fig, ax = plt.subplots(figsize=config.figsize, dpi=config.dpi)
        
        n, bins_edges, patches = ax.hist(data[column], bins=bins, alpha=0.7, 
                                        color=sns.color_palette(config.color_palette)[0],
                                        edgecolor='black')
        
        # Add statistics text
        mean_val = data[column].mean()
        std_val = data[column].std()
        ax.axvline(mean_val, color='red', linestyle='--', linewidth=2, label=f'Mean: {mean_val:.2f}')
        ax.axvline(mean_val + std_val, color='orange', linestyle='--', alpha=0.7, label=f'+1 STD: {mean_val + std_val:.2f}')
        ax.axvline(mean_val - std_val, color='orange', linestyle='--', alpha=0.7, label=f'-1 STD: {mean_val - std_val:.2f}')
        
        ax.set_title(config.title, fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel(config.xlabel or column, fontsize=12)
        ax.set_ylabel(config.ylabel or 'Frequency', fontsize=12)
        
        if config.legend:
            ax.legend(fontsize=10)
        
        if config.grid:
            ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        self.figures.append(fig)
        return fig
    
    def create_box_plot(self, data: pd.DataFrame, columns: Union[str, List[str]],
                       config: Optional[ChartConfig] = None) -> plt.Figure:
        """
        Create a box plot.
        
        Args:
            data: DataFrame containing the data
            columns: Column name(s) to plot
            config: Optional chart configuration
            
        Returns:
            Matplotlib figure object
        """
        config = config or self.config
        
        fig, ax = plt.subplots(figsize=config.figsize, dpi=config.dpi)
        
        if isinstance(columns, str):
            columns = [columns]
        
        box_data = [data[col].dropna() for col in columns]
        
        bp = ax.boxplot(box_data, labels=columns, patch_artist=True)
        
        # Color the boxes
        colors = sns.color_palette(config.color_palette, len(columns))
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        
        ax.set_title(config.title, fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel(config.xlabel or 'Categories', fontsize=12)
        ax.set_ylabel(config.ylabel or 'Values', fontsize=12)
        
        if config.grid:
            ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        self.figures.append(fig)
        return fig
    
    def create_heatmap(self, data: pd.DataFrame, config: Optional[ChartConfig] = None) -> plt.Figure:
        """
        Create a correlation heatmap.
        
        Args:
            data: DataFrame containing numerical data
            config: Optional chart configuration
            
        Returns:
            Matplotlib figure object
        """
        config = config or self.config
        
        fig, ax = plt.subplots(figsize=config.figsize, dpi=config.dpi)
        
        # Calculate correlation matrix
        corr_matrix = data.select_dtypes(include=[np.number]).corr()
        
        # Create heatmap
        sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', center=0,
                   square=True, fmt='.2f', cbar_kws={'shrink': 0.8}, ax=ax)
        
        ax.set_title(config.title or 'Correlation Heatmap', fontsize=16, fontweight='bold', pad=20)
        
        plt.tight_layout()
        
        self.figures.append(fig)
        return fig
    
    def create_pie_chart(self, data: pd.DataFrame, column: str, 
                        config: Optional[ChartConfig] = None) -> plt.Figure:
        """
        Create a pie chart.
        
        Args:
            data: DataFrame containing the data
            column: Column name with categorical data
            config: Optional chart configuration
            
        Returns:
            Matplotlib figure object
        """
        config = config or self.config
        
        fig, ax = plt.subplots(figsize=config.figsize, dpi=config.dpi)
        
        # Count values
        value_counts = data[column].value_counts()
        
        # Create pie chart
        colors = sns.color_palette(config.color_palette, len(value_counts))
        wedges, texts, autotexts = ax.pie(value_counts.values, labels=value_counts.index,
                                          autopct='%1.1f%%', colors=colors, startangle=90)
        
        # Enhance text appearance
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
        
        ax.set_title(config.title, fontsize=16, fontweight='bold', pad=20)
        
        plt.tight_layout()
        
        self.figures.append(fig)
        return fig
    
    def statistical_summary(self, data: pd.DataFrame, column: str) -> StatisticalSummary:
        """
        Calculate comprehensive statistical summary for a column.
        
        Args:
            data: DataFrame containing the data
            column: Column name to analyze
            
        Returns:
            StatisticalSummary object with all statistics
        """
        series = data[column].dropna()
        
        from scipy import stats
        
        return StatisticalSummary(
            mean=series.mean(),
            median=series.median(),
            std=series.std(),
            min_val=series.min(),
            max_val=series.max(),
            q25=series.quantile(0.25),
            q75=series.quantile(0.75),
            skewness=stats.skew(series),
            kurtosis=stats.kurtosis(series),
            count=len(series),
            missing_values=data[column].isna().sum()
        )
    
    def save_figure(self, figure: plt.Figure, filename: str, 
                   format: str = "png", dpi: int = 300) -> None:
        """
        Save figure to file.
        
        Args:
            figure: Matplotlib figure to save
            filename: Output filename
            format: File format (png, jpg, pdf, svg)
            dpi: Resolution for raster formats
        """
        figure.savefig(filename, format=format, dpi=dpi, bbox_inches='tight',
                      transparent=self.config.transparent)
        print(f"Figure saved to {filename}")
    
    def figure_to_base64(self, figure: plt.Figure, format: str = "png") -> str:
        """
        Convert figure to base64 string for embedding in HTML.
        
        Args:
            figure: Matplotlib figure to convert
            format: Image format
            
        Returns:
            Base64 encoded image string
        """
        buffer = io.BytesIO()
        figure.savefig(buffer, format=format, bbox_inches='tight')
        buffer.seek(0)
        
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/{format};base64,{image_base64}"
    
    def create_dashboard(self, data: pd.DataFrame, title: str = "Data Dashboard") -> str:
        """
        Create an HTML dashboard with multiple visualizations.
        
        Args:
            data: DataFrame to visualize
            title: Dashboard title
            
        Returns:
            HTML string for the dashboard
        """
        # Create multiple charts
        numerical_cols = data.select_dtypes(include=[np.number]).columns.tolist()
        categorical_cols = data.select_dtypes(include=['object']).columns.tolist()
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{title}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
                .dashboard {{ max-width: 1200px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .chart-container {{ margin-bottom: 30px; text-align: center; }}
                .chart-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
                .stats-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
                .stats-table th, .stats-table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                .stats-table th {{ background-color: #f2f2f2; }}
                h2 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
            </style>
        </head>
        <body>
            <div class="dashboard">
                <div class="header">
                    <h1>{title}</h1>
                    <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
        """
        
        # Add data overview
        html_content += f"""
                <h2>Data Overview</h2>
                <table class="stats-table">
                    <tr><th>Metric</th><th>Value</th></tr>
                    <tr><td>Total Rows</td><td>{len(data)}</td></tr>
                    <tr><td>Total Columns</td><td>{len(data.columns)}</td></tr>
                    <tr><td>Numerical Columns</td><td>{len(numerical_cols)}</td></tr>
                    <tr><td>Categorical Columns</td><td>{len(categorical_cols)}</td></tr>
                </table>
        """
        
        # Add statistical summaries for numerical columns
        if numerical_cols:
            html_content += "<h2>Statistical Summary</h2><table class='stats-table'><tr><th>Column</th><th>Mean</th><th>Std</th><th>Min</th><th>Max</th></tr>"
            
            for col in numerical_cols[:5]:  # Limit to first 5 columns
                stats = self.statistical_summary(data, col)
                html_content += f"""
                <tr>
                    <td>{col}</td>
                    <td>{stats.mean:.2f}</td>
                    <td>{stats.std:.2f}</td>
                    <td>{stats.min_val:.2f}</td>
                    <td>{stats.max_val:.2f}</td>
                </tr>
                """
            html_content += "</table>"
        
        # Add charts
        if len(numerical_cols) >= 2:
            # Scatter plot
            fig = self.create_scatter_plot(data, numerical_cols[0], numerical_cols[1])
            chart_b64 = self.figure_to_base64(fig)
            html_content += f"""
                <div class="chart-container">
                    <h2>Scatter Plot: {numerical_cols[0]} vs {numerical_cols[1]}</h2>
                    <img src="{chart_b64}" style="max-width: 100%; height: auto;">
                </div>
            """
        
        if numerical_cols:
            # Histogram
            fig = self.create_histogram(data, numerical_cols[0])
            chart_b64 = self.figure_to_base64(fig)
            html_content += f"""
                <div class="chart-container">
                    <h2>Distribution: {numerical_cols[0]}</h2>
                    <img src="{chart_b64}" style="max-width: 100%; height: auto;">
                </div>
            """
        
        if categorical_cols:
            # Pie chart
            fig = self.create_pie_chart(data, categorical_cols[0])
            chart_b64 = self.figure_to_base64(fig)
            html_content += f"""
                <div class="chart-container">
                    <h2>Distribution: {categorical_cols[0]}</h2>
                    <img src="{chart_b64}" style="max-width: 100%; height: auto;">
                </div>
            """
        
        if len(numerical_cols) >= 2:
            # Correlation heatmap
            fig = self.create_heatmap(data[numerical_cols])
            chart_b64 = self.figure_to_base64(fig)
            html_content += f"""
                <div class="chart-container">
                    <h2>Correlation Heatmap</h2>
                    <img src="{chart_b64}" style="max-width: 100%; height: auto;">
                </div>
            """
        
        html_content += """
            </div>
        </body>
        </html>
        """
        
        return html_content
    
    def clear_figures(self) -> None:
        """Clear all cached figures to free memory."""
        for fig in self.figures:
            plt.close(fig)
        self.figures.clear()

def generate_sample_data() -> pd.DataFrame:
    """Generate sample data for demonstration."""
    np.random.seed(42)
    
    n_samples = 1000
    
    data = {
        'date': pd.date_range('2023-01-01', periods=n_samples, freq='D'),
        'sales': np.random.normal(1000, 200, n_samples) + np.sin(np.arange(n_samples) * 0.1) * 100,
        'marketing_spend': np.random.uniform(100, 500, n_samples),
        'customer_satisfaction': np.random.uniform(3.0, 5.0, n_samples),
        'product_category': np.random.choice(['Electronics', 'Clothing', 'Books', 'Home'], n_samples),
        'region': np.random.choice(['North', 'South', 'East', 'West'], n_samples),
        'returns': np.random.poisson(5, n_samples)
    }
    
    df = pd.DataFrame(data)
    
    # Add some correlations
    df['sales'] = df['sales'] + df['marketing_spend'] * 0.5 + np.random.normal(0, 50, n_samples)
    df['customer_satisfaction'] = np.clip(df['customer_satisfaction'] - df['returns'] * 0.1, 1.0, 5.0)
    
    return df

def main():
    """Example usage of the DataVisualizer class."""
    # Generate sample data
    data = generate_sample_data()
    print("Sample data generated:")
    print(data.head())
    print(f"\nData shape: {data.shape}")
    
    # Create visualizer
    visualizer = DataVisualizer()
    
    try:
        # Create various charts
        print("\nCreating visualizations...")
        
        # Line plot
        fig1 = visualizer.create_line_plot(
            data.head(100), 'date', 'sales',
            ChartConfig(title="Sales Trend", xlabel="Date", ylabel="Sales ($)")
        )
        visualizer.save_figure(fig1, "sales_trend.png")
        
        # Scatter plot
        fig2 = visualizer.create_scatter_plot(
            data, 'marketing_spend', 'sales', color='customer_satisfaction',
            ChartConfig(title="Marketing Spend vs Sales", xlabel="Marketing Spend ($)", ylabel="Sales ($)")
        )
        visualizer.save_figure(fig2, "marketing_vs_sales.png")
        
        # Histogram
        fig3 = visualizer.create_histogram(
            data, 'customer_satisfaction',
            ChartConfig(title="Customer Satisfaction Distribution", xlabel="Satisfaction Score", ylabel="Frequency")
        )
        visualizer.save_figure(fig3, "satisfaction_histogram.png")
        
        # Box plot
        fig4 = visualizer.create_box_plot(
            data, ['sales', 'marketing_spend'],
            ChartConfig(title="Sales and Marketing Spend Distribution", xlabel="Metrics", ylabel="Values ($)")
        )
        visualizer.save_figure(fig4, "box_plot.png")
        
        # Pie chart
        fig5 = visualizer.create_pie_chart(
            data, 'product_category',
            ChartConfig(title="Product Category Distribution")
        )
        visualizer.save_figure(fig5, "category_pie.png")
        
        # Statistical summary
        stats = visualizer.statistical_summary(data, 'sales')
        print(f"\nSales Statistics:")
        print(f"Mean: ${stats.mean:.2f}")
        print(f"Median: ${stats.median:.2f}")
        print(f"Std Dev: ${stats.std:.2f}")
        print(f"Range: ${stats.min_val:.2f} - ${stats.max_val:.2f}")
        
        # Create dashboard
        dashboard_html = visualizer.create_dashboard(data, "Sales Analytics Dashboard")
        with open("dashboard.html", "w") as f:
            f.write(dashboard_html)
        print("\nDashboard saved to dashboard.html")
        
        print("\nAll visualizations created successfully!")
        
    except Exception as e:
        print(f"Error creating visualizations: {e}")
    finally:
        # Clean up
        visualizer.clear_figures()

if __name__ == "__main__":
    main()