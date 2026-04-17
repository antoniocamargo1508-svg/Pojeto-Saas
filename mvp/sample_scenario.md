# Cenário de Simulação Realista

Este arquivo descreve um cenário mais completo para testar o MVP com dados próximos de um negócio real.

## Objetivo

- Avaliar a qualidade dos dados de receita e despesa.
- Verificar concentração de custos por categoria.
- Simular tendência de 3 e 6 meses para receita e despesa.
- Entender o risco de estouro do orçamento e o prazo de execução.

## Colunas recomendadas

Use um arquivo com pelo menos as colunas:

- `date` (data da transação)
- `category` (categoria do gasto ou receita)
- `record_type` (`revenue` ou `expense`)
- `budgeted` (valor orçado)
- `actual` ou `value` (valor realizado)
- `description` (opcional, texto livre)

## Categorias sugeridas

- Receita recorrente
- Receita eventuais
- Vendas
- Marketing digital
- Aquisição de clientes
- Salários e benefícios
- Infraestrutura e nuvem
- Licenças de software
- Escritório e serviços gerais
- Suporte técnico
- Desenvolvimento de produto
- Despesas administrativas

## Fases do cenário

1. **Receita**: inclua receita recorrente e receitas pontuais de venda ou serviços.
2. **Despesas fixas**: salários, aluguel, licenças e infraestrutura.
3. **Despesas variáveis**: marketing, aquisição, suporte sazonal, comissões.
4. **Orçamento vs realizado**: envie valores orçados diferentes dos realizados para testar desvios.
5. **Tendência**: use pelo menos 6 meses de dados para que as médias móveis 3M e 6M façam sentido.

## Como usar neste MVP

- Importe o arquivo CSV/Excel via `Upload`.
- Salve o recorte e acesse o `Dashboard`.
- Leia os alertas e o `Guia de cálculo dos indicadores` para entender cada número.
- Compare as categorias mais impactantes e as taxas de concentração.

## Como interpretar os indicadores

- `Execução do orçamento`: mede se o gasto real já ultrapassou o valor orçado.
- `Índice não previsto`: mostra quantas transações não estavam previstas no orçamento.
- `Top 5 concentração`: indica se poucas categorias dominam o gasto total.
- `Prob. estouro`: risco modelado a partir do padrão atual de despesas.
- `Tendência 3M / 6M`: mostra se receita e despesa estão subindo ou estabilizando.

## Dica

Quanto mais histórico de dados você usar, melhor serão as ideias de tendência e de risco. Um cenário com 9 a 12 meses de dados permite analisar ciclos e avaliar a robustez do orçamento.
