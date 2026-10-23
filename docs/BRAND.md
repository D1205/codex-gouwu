# codex的构物 · 标志

<img src="../ui/public/brand/logo.svg" alt="codex的构物标志" width="128" height="128">

等轴立方体构架留出一个装配口，内部的折线形成空间的转折，也隐含 G 的轮廓。标志使用深青底 `#244b59` 与米白线条 `#f7f6ef`，不加渐变、阴影或细小装饰；图形与文字分开，便于小尺寸显示。

矢量源文件为 [`ui/public/brand/logo.svg`](../ui/public/brand/logo.svg)。界面页头和欢迎区直接使用它，浏览器使用同源的 [`favicon.svg`](../ui/public/favicon.svg)。Windows 程序与桌面快捷方式使用 [`app.ico`](../ui/public/brand/app.ico)，内含 16、20、24、32、40、48、64、128 和 256 像素图层。PNG 预览为 [`app-256.png`](../ui/public/brand/app-256.png)。

修改 SVG 后，用已包含 Pillow 的构建环境重新生成位图：

```powershell
python scripts/build-brand-icons.py
```

生成脚本只在构建时使用 Pillow；应用无需额外安装图像渲染依赖。SVG 元素限定为源文件中的矩形和圆角折线。页面内保留文字名称，图形不替代可访问名称。

本地打开 [`brand-preview.html`](brand-preview.html) 可比较图标尺寸与界面配色。
