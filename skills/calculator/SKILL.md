---
name: calculator
description: 精确计算器
version: 1.0.0
triggers: 计算,算术,运算,公式,数学
---

## 精确计算指南

遇到数学计算需求时，使用 Python 执行精确运算，避免浮点误差：

### 基础运算
  execute('python -c "print(123.45 * 67.89)"')
  评估表达式使用 eval：
  execute('python -c "print(eval("(2+3)*4"))"')

### 注意事项
- 优先使用 python -c 而非 python -c "import ..."
- 复杂表达式用 eval() 包裹
- 结果如果含小数，保留足够精度
- 大数运算使用 Python 的任意精度整数