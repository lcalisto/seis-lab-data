# Formatos de ficheiros suportados

Esta página documenta os formatos de ficheiros presentes no arquivo de dados marinhos e o
seu estado de suporte no pipeline de extração do SeisLabData.

## Formatos raster GDAL

Estes formatos são lidos através de drivers raster GDAL. O extrator consegue obter: caixa
delimitadora (bounding box), código CRS/EPSG, número de bandas, resolução de píxel e valor
nodata.

### GeoTIFF

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.tif`, `.tiff` |
| Tipo de média | `image/tiff` |
| Driver GDAL | GTiff |
| Categorias | Batimetria, Backscatter |
| Fases | Controlo de qualidade, Dados processados, Dados interpretados |

Formato raster georreferenciado com CRS e metadados incorporados. Amplamente suportado em
ferramentas SIG. Utilizado como ficheiro principal para grelhas de batimetria/backscatter
processadas e produtos interpretados.

### Grelha XYZ

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.xyz` |
| Tipo de média | `text/plain` |
| Driver GDAL | XYZ |
| Categorias | Batimetria, Backscatter |
| Fases | Dados em bruto, Controlo de qualidade, Dados interpretados |

Formato de nuvem de pontos em texto simples com colunas X, Y, Z. Utilizado como ficheiro
principal para dados de batimetria em bruto/controlo de qualidade e como ficheiro secundário
nalgumas fases. O GDAL lê-o como um conjunto de dados raster em grelha. Quando os seus pontos
não formam uma grelha regular, como no caso das sondagens aceites, o GDAL rejeita-o, e a descoberta
lê em vez disso 128 janelas de 64 KB distribuídas pelo ficheiro, tomando a extensão dos pontos nelas
contidos e estimando o número de pontos. Nos ficheiros medidos, essa extensão ficou aquém da exata
em menos de 1% da sua dimensão.

### ASCII Grid

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.asc` |
| Tipo de média | `text/plain` |
| Driver GDAL | AAIGrid |
| Categorias | Batimetria, Backscatter |
| Fases | Dados interpretados |

Formato raster ASCII da ESRI. O cabeçalho define as dimensões da grelha, tamanho da célula,
origem e valor nodata, seguido de valores de célula separados por espaços. Utilizado como
ficheiro principal para produtos interpretados.

### Float Grid

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.flt` + `.hdr` |
| Tipo de média | `application/octet-stream` |
| Driver GDAL | EHdr |
| Categorias | Batimetria, Backscatter |
| Fases | Dados processados, Dados interpretados |

Formato raster binário que armazena valores de vírgula flutuante IEEE de 32 bits em ordem
row-major. Requer um ficheiro de cabeçalho `.hdr` complementar contendo metadados da grelha
(ncols, nrows, cellsize, nodata_value, byteorder). Utilizado como ficheiro secundário para
dados processados e como principal/secundário para produtos interpretados.

### NetCDF

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.nc`, `.nc4` |
| Tipo de média | `application/x-netcdf` |
| Driver GDAL | netCDF |
| Categorias | Batimetria, Backscatter |
| Fases | Dados processados, Dados interpretados |

Network Common Data Form, formato binário auto-descritivo amplamente utilizado em dados
oceanográficos, atmosféricos e climáticos. O GDAL consegue ler ficheiros NetCDF como conjuntos
de dados raster, mas apenas quando seguem as convenções CF (Climate and Forecast) com
variáveis de coordenadas, dimensões e atributos de mapeamento de grelha devidamente definidos.
Ficheiros NetCDF não estruturados ou que não sigam a estrutura padrão CF não podem ser lidos
pelo GDAL.

### CSV

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.csv` |
| Tipo de média | `text/csv` |
| Driver GDAL | CSV |
| Categorias | Batimetria, Backscatter |
| Fases | Dados em bruto, Controlo de qualidade, Dados interpretados |

Ficheiro de texto com valores separados por vírgulas ou delimitadores, contendo dados de
pontos (X, Y, Z ou lon, lat, valor). Semelhante ao XYZ mas com linha de cabeçalho e nomeação
flexível de colunas. O OGR lê-o como um conjunto de dados vetorial de pontos; pode também
ser tratado como raster via VRT.


## Formatos vetoriais OGR

Estes formatos são lidos através de drivers vetoriais OGR. O extrator consegue obter: caixa
delimitadora (bounding box), código CRS/EPSG, contagem de elementos e tipo de geometria.

### Shapefile

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.shp` + `.shx` + `.dbf` |
| Tipo de média | `application/x-shapefile` |
| Driver OGR | ESRI Shapefile |
| Categorias | Batimetria |
| Fases | Dados em bruto, Controlo de qualidade, Dados processados, Dados interpretados |

Formato vetorial ESRI que armazena geometrias de pontos, linhas ou polígonos com dados de
atributos. Os ficheiros complementares `.shx` (índice) e `.dbf` (atributos) são obrigatórios.
Utilizado como ficheiro secundário em todas as fases do fluxo de trabalho.

As _shapefiles_ são descarregadas como um arquivo zip que contém o ficheiro `.shp` juntamente com
todos os seus ficheiros complementares (todos os ficheiros da mesma diretoria que partilham o seu
nome, como `.shx`, `.dbf`, `.prj`, `.cpg` ou `.shp.xml`).

### CSV

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.csv` |
| Tipo de média | `text/csv` |
| Driver OGR | CSV |
| Categorias | Batimetria, Backscatter |
| Fases | Dados em bruto, Controlo de qualidade, Dados interpretados |

Ficheiro de texto com valores separados por vírgulas ou delimitadores, contendo dados de pontos
com colunas de coordenadas (X/Y, lon/lat). O OGR lê-o como um conjunto de dados vetorial de
pontos quando as colunas com coordenadas são identificadas. Também listado nos formatos raster
GDAL, pois pode ser tratado como raster em grelha via VRT.

### File Geodatabase

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.gdb` (diretório) |
| Tipo de média | `application/x-filegdb` |
| Driver OGR | OpenFileGDB |
| Categorias | Batimetria, Backscatter |
| Fases | Dados em bruto, Controlo de qualidade, Dados processados, Dados interpretados |

ESRI File Geodatabase, um diretório contendo múltiplos ficheiros de base de dados que
armazenam conjuntos de dados vetoriais e raster. Utilizado como ficheiro secundário para
dados em bruto/controlo de qualidade/processados e como principal/secundário para produtos
interpretados. Acesso apenas de leitura através do driver OpenFileGDB (sem necessidade de
licença ESRI).

### GeoJSON

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.geojson`, `.json` |
| Tipo de média | `application/geo+json` |
| Driver OGR | GeoJSON |
| Categorias | Batimetria, Backscatter |
| Fases | Dados processados, Dados interpretados |

Formato aberto para codificação de estruturas de dados geográficos em JSON. Suporta geometrias
de pontos, linhas, polígonos e multi-geometrias com propriedades associadas. Utiliza sempre
WGS 84 (EPSG:4326) como sistema de referência de coordenadas.

### GeoPackage

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.gpkg` |
| Tipo de média | `application/geopackage+sqlite3` |
| Driver OGR | GPKG |
| Categorias | Batimetria, Backscatter |
| Fases | Dados processados, Dados interpretados |

Norma aberta OGC baseada em SQLite. Permite armazenar dados vetoriais e raster num único
ficheiro. Suporta múltiplas camadas, índices espaciais e CRS arbitrário. Alternativa moderna
ao Shapefile e ao File Geodatabase.

### KML/KMZ

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.kml`, `.kmz` |
| Tipo de média | `application/vnd.google-earth.kml+xml` |
| Driver OGR | KML / LIBKML |
| Categorias | Batimetria, Backscatter |
| Fases | Dados interpretados |

Formato de marcação do Google Earth para visualização geográfica. O KML é baseado em XML;
o KMZ é um arquivo comprimido (ZIP) contendo um ficheiro KML e recursos opcionais. Suporta
geometrias de pontos, linhas e polígonos. Utiliza sempre WGS 84 (EPSG:4326). O OGR consegue
ler tanto KML como KMZ através dos drivers KML ou LIBKML.


## Formatos especializados (futuro)

Estes formatos requerem extratores dedicados que ainda não estão implementados. Serão
adicionados em iterações futuras.

### CSAR

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.csar` |
| Tipo de média | `application/octet-stream` |
| Categorias | Batimetria, Backscatter |
| Fases | Dados processados |

Ficheiro CARIS Spatial Archive. Formato raster proprietário para dados de batimetria e
elevação em grelha. Utilizado como ficheiro principal para dados processados. Requer
software/licença CARIS para acesso completo.

### KMALL

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.kmall` |
| Categorias | Batimetria, Backscatter |
| Fases | Dados em bruto |

Formato binário baseado em datagramas dos sistemas de ecossonda multifeixe Kongsberg. Contém
dados de posição (latitude, longitude, marca temporal), medições de profundidade e indicadores
de qualidade. O datagrama `#SPO` fornece dados de posição; o `#MRZ` fornece
profundidade/refletividade.

Um módulo Python para leitura de datagramas está disponível no GitHub.

A descoberta não lê os ficheiros KMALL por inteiro: obtém a extensão espacial e a extensão temporal
de 16 janelas de 256 KB, nas duas pontas do ficheiro e igualmente espaçadas entre elas. As duas
pontas de uma linha de levantamento são sempre lidas, enquanto os extremos de uma trajetória curva
podem falhar pela distância percorrida entre duas janelas.

### SEG-Y

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.segy`, `.sgy` |
| Categorias | Sísmica |
| Fases | Dados em bruto |

Formato padrão de troca de dados sísmicos (SEG-Y Revisão 2.0). Estrutura:

- Cabeçalho de texto (3200 bytes)
- Cabeçalho binário (400 bytes)
- Cabeçalho de texto estendido (opcional)
- Traços (traços sísmicos individuais com cabeçalhos de 240 bytes)

Bibliotecas Python: **segyio** (mantida ativamente, pela Equinor) e **segpy**.

### JSF

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.jsf` |
| Categorias | Sísmica |
| Fases | Dados em bruto |

Formato de dados de sonar EdgeTech. Formato binário com estrutura de cabeçalho definida
(JSFDefs.h). Utilizado para dados em bruto de perfilador de sub-fundo (SBP).

### P1/11

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.p111` |
| Categorias | Dados de posição geofísica |
| Fases | Dados em bruto |

Formato de troca de dados de posição geofísica. Pode ser importado utilizando o plugin
SeisPos_Import do QGIS.


## Outros formatos

### Projeto HIPS

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | Diretório (estrutura proprietária) |
| Categorias | Batimetria |
| Fases | Dados processados |

Diretório de projeto CARIS HIPS e SIPS. Formato proprietário contendo dados multifeixe
processados. Não está prevista extração automatizada, tratado como um diretório opaco.

### XLS

| Propriedade | Valor |
|-------------|-------|
| Extensão(ões) | `.xls`, `.xlsx` |
| Tipo de média | `application/vnd.ms-excel` |
| Categorias | Batimetria |
| Fases | Dados em bruto, Controlo de qualidade, Dados processados |

Dados tabulares em folha de cálculo. Utilizado como ficheiro secundário para metadados ou
informação auxiliar. Sem suporte GDAL/OGR — necessitaria de um leitor dedicado caso a
extração seja necessária.
