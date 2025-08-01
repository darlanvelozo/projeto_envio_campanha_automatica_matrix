# views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db import connection
from django.utils import timezone
from django.urls import reverse 
import json
import pandas as pd
import unicodedata
import time
import logging
from io import StringIO
import threading
import requests
from .models import (
    TemplateSQL, CredenciaisBancoDados, CredenciaisHubsoft, 
    ConsultaExecucao, ClienteConsultado, ConsultaCliente,
    MatrixAPIConfig, HSMTemplate, EnvioHSMMatrix, EnvioHSMIndividual
)
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

def normalizar_texto(texto: str) -> str:
    """Normaliza o texto removendo acentos e convertendo para maiúsculas."""
    if not isinstance(texto, str):
        return ''
    nfkd_form = unicodedata.normalize('NFD', texto)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).upper()

class HubsoftAPI:
    def __init__(self, credenciais):
        self.credenciais = credenciais
        self._access_token = None
        self.session = requests.Session()
        self.timeout = 60

    def _get_token(self):
        """Obtém um novo token de acesso da API e o armazena."""
        logger.info(f"Solicitando novo token de acesso para {self.credenciais.url_base}")
        auth_payload = {
            "client_id": self.credenciais.client_id,
            "client_secret": self.credenciais.client_secret,
            "username": self.credenciais.username,
            "password": self.credenciais.password,
            "grant_type": "password"
        }
        try:
            response = requests.post(
                self.credenciais.url_token,
                json=auth_payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            token_data = response.json()
            self._access_token = token_data.get('access_token')
            
            if not self._access_token:
                logger.error("Token de acesso não encontrado na resposta da API.")
                raise ValueError("Falha ao obter token: 'access_token' ausente na resposta.")
            
            self.session.headers.update({
                'Authorization': f'Bearer {self._access_token}',
                'Content-Type': 'application/json'
            })
            logger.info("Token obtido e sessão configurada com sucesso.")

        except requests.RequestException as e:
            logger.error(f"Erro de rede ao obter token: {e}")
            raise

    def _ensure_token(self):
        """Garante que um token de acesso válido exista antes de fazer uma chamada."""
        if not self._access_token:
            self._get_token()

    def consultar_cliente_financeiro(self, codigo_cliente):
        """Consulta dados financeiros do cliente na API"""
        try:
            self._ensure_token()
            
            endpoint = f"/api/v1/integracao/cliente/financeiro?busca=codigo_cliente&termo_busca={codigo_cliente}"
            url = f"{self.credenciais.url_base}{endpoint}"
            
            logger.info(f"Consultando cliente {codigo_cliente}")
            
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            logger.info(f"Resposta da consulta para {codigo_cliente}: Status {response.status_code}")
            return response.json()

        except requests.RequestException as e:
            logger.error(f"Erro na consulta do cliente {codigo_cliente}: {e}")
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 401:
                logger.warning("Recebido status 401. O token pode ter expirado. Tentando obter um novo na próxima chamada.")
                self._access_token = None
            return None
        except Exception as e:
            logger.error(f"Erro inesperado ao consultar cliente {codigo_cliente}: {e}")
            return None

def pagina_processar_consulta(request):
    """Página principal para configurar e executar consultas"""
    templates = TemplateSQL.objects.filter(ativo=True)
    credenciais_hubsoft = CredenciaisHubsoft.objects.filter(ativo=True)
    credenciais_banco = CredenciaisBancoDados.objects.filter(ativo=True)
    
    context = {
        'templates': templates,
        'credenciais_hubsoft': credenciais_hubsoft,
        'credenciais_banco': credenciais_banco
    }
    
    return render(request, 'campanhas/processar_consulta.html', context)

def obter_variaveis_template(request, template_id):
    """Retorna as variáveis de um template específico via AJAX"""
    try:
        template = TemplateSQL.objects.get(id=template_id, ativo=True)
        variaveis = template.get_variaveis_configuradas()
        
        return JsonResponse({
            'status': 'success',
            'variaveis': variaveis,
            'template_titulo': template.titulo
        })
    except TemplateSQL.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Template não encontrado'
        }, status=404)
    except Exception as e:
        logger.error(f"Erro ao obter variáveis do template {template_id}: {e}")
        return JsonResponse({
            'status': 'error',
            'message': f'Erro interno: {str(e)}'
        }, status=500)

def executar_consulta_sql(credencial_banco, template_sql, valores_variaveis=None):
    """Executa uma consulta SQL no banco especificado, processando variáveis se necessário"""
    try:
        # Processa a query substituindo variáveis se fornecidas
        if valores_variaveis and hasattr(template_sql, 'substituir_variaveis'):
            query = template_sql.substituir_variaveis(valores_variaveis)
        else:
            query = template_sql.consulta_sql if hasattr(template_sql, 'consulta_sql') else template_sql
        
        # Limpa a query preservando a estrutura SQL
        query = query.strip()
        
        # Log detalhado para debug
        logger.info(f"Executando consulta SQL com credencial: {credencial_banco.titulo}")
        logger.info(f"Query SQL original (primeiros 500 chars): {template_sql.consulta_sql[:500]}...")
        if valores_variaveis:
            logger.info(f"Variáveis utilizadas: {valores_variaveis}")
        logger.info(f"Query SQL processada (primeiros 500 chars): {query[:500]}...")
        logger.info(f"Tamanho da query: {len(query)} caracteres")
        
        # Conectar ao PostgreSQL
        conn = psycopg2.connect(
            host=credencial_banco.host,
            port=credencial_banco.porta,
            database=credencial_banco.banco,
            user=credencial_banco.usuario,
            password=credencial_banco.senha
        )
        
        # Configurar o cursor para retornar dicionários
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Executa a query como um bloco completo
        cursor.execute(query)
        results = cursor.fetchall()
        
        # Converte para lista de dicionários
        results = [dict(row) for row in results]
        
        logger.info(f"Consulta SQL executada com sucesso. {len(results)} registros encontrados.")
        
        cursor.close()
        conn.close()
        
        return results
    except Exception as e:
        logger.error(f"Erro ao executar consulta SQL: {str(e)}")
        logger.error(f"Query que causou o erro: {query}")
        raise

def obter_fatura_por_id(dados: dict, id_fatura: str) -> dict | None:
    """Obtém uma fatura específica pelo ID dentro dos dados do cliente."""
    if not dados or 'faturas' not in dados:
        return None
    for fatura in dados.get('faturas', []):
        if str(fatura.get('id_fatura')) == str(id_fatura):
            return fatura
    return None

def converter_data_br_para_iso(data_str):
    """Converte data do formato DD/MM/YYYY para YYYY-MM-DD"""
    if not data_str:
        return None
    try:
        from datetime import datetime
        data = datetime.strptime(data_str, '%d/%m/%Y')
        return data.strftime('%Y-%m-%d')
    except Exception as e:
        logger.error(f"Erro ao converter data {data_str}: {e}")
        return None

def processar_cliente_api(api_client, cliente_data, execucao):
    """Processa um cliente individual consultando a API"""
    codigo_cliente = cliente_data.get('codigo_cliente')
    id_fatura_desejada = cliente_data.get('id_fatura')
    
    # Garantir que sempre temos um cliente registrado, mesmo com erro
    cliente_obj = None
    error_msg = None
    
    try:
        # Consulta a API
        dados_cliente = api_client.consultar_cliente_financeiro(codigo_cliente)
        
        if not dados_cliente:
            error_msg = "Falha ao consultar dados na API - resposta vazia ou erro de conexão"
            raise Exception(error_msg)
        
        # Busca a fatura específica
        fatura = obter_fatura_por_id(dados_cliente, id_fatura_desejada)
        
        if not fatura:
            error_msg = f"Fatura {id_fatura_desejada} não encontrada nos dados retornados pela API"
            raise Exception(error_msg)
        
        # Cria ou atualiza o cliente consultado (agora com credencial_banco para unicidade)
        cliente_obj, created = ClienteConsultado.objects.get_or_create(
            codigo_cliente=codigo_cliente,
            credencial_banco=execucao.credencial_banco,  # Inclui a credencial para unicidade por empresa
            defaults={
                'nome_razaosocial': normalizar_texto(cliente_data.get('nome_razaosocial', '')),
                'telefone_corrigido': cliente_data.get('TelefoneCorrigido', ''),
                'id_fatura': id_fatura_desejada,
                'data_criacao': timezone.now()
            }
        )
        
        # Converte a data de vencimento para o formato correto
        data_vencimento = fatura.get('data_vencimento')
        if data_vencimento:
            data_vencimento = converter_data_br_para_iso(data_vencimento)
        
        # Atualiza dados da fatura
        cliente_obj.vencimento_fatura = data_vencimento
        cliente_obj.valor_fatura = fatura.get('valor')
        cliente_obj.pix = fatura.get('pix_copia_cola')
        cliente_obj.codigo_barras = fatura.get('codigo_barras')
        cliente_obj.link_boleto = fatura.get('link')
        cliente_obj.data_atualizacao = timezone.now()
        cliente_obj.save()
        
        # Registra a consulta (usa get_or_create para evitar duplicatas)
        consulta_cliente, created = ConsultaCliente.objects.get_or_create(
            execucao=execucao,
            cliente=cliente_obj,
            defaults={
                'dados_originais_sql': cliente_data,
                'dados_api_response': dados_cliente,
                'sucesso_api': True
            }
        )
        
        # Se já existia, atualiza os dados
        if not created:
            consulta_cliente.dados_originais_sql = cliente_data
            consulta_cliente.dados_api_response = dados_cliente
            consulta_cliente.sucesso_api = True
            consulta_cliente.erro_api = None
            consulta_cliente.save()
            logger.info(f"Atualizando consulta existente para cliente {codigo_cliente}")
        
        return cliente_obj, None
        
    except Exception as e:
        # Se ainda não temos error_msg, captura o erro atual
        if not error_msg:
            error_msg = f"Erro ao processar cliente {codigo_cliente}: {str(e)}"
        
        logger.error(error_msg)
        
        # SEMPRE registra o erro, mesmo que o cliente não exista ainda
        try:
            # Garante que o cliente existe para poder registrar o erro
            if not cliente_obj and codigo_cliente:
                cliente_obj, _ = ClienteConsultado.objects.get_or_create(
                    codigo_cliente=codigo_cliente,
                    defaults={
                        'nome_razaosocial': normalizar_texto(cliente_data.get('nome_razaosocial', '')) or 'Nome não disponível',
                        'telefone_corrigido': cliente_data.get('TelefoneCorrigido', ''),
                        'id_fatura': id_fatura_desejada,
                        'data_criacao': timezone.now()
                    }
                )
            
            # Registra a consulta com erro (sempre, independente de ter cliente ou não)
            if cliente_obj:
                consulta_cliente, created = ConsultaCliente.objects.get_or_create(
                    execucao=execucao,
                    cliente=cliente_obj,
                    defaults={
                        'dados_originais_sql': cliente_data,
                        'sucesso_api': False,
                        'erro_api': error_msg,
                        'dados_api_response': None
                    }
                )
                
                # Se já existia, atualiza os dados do erro
                if not created:
                    consulta_cliente.dados_originais_sql = cliente_data
                    consulta_cliente.sucesso_api = False
                    consulta_cliente.erro_api = error_msg
                    consulta_cliente.dados_api_response = None
                    consulta_cliente.save()
                    logger.info(f"Atualizando erro da consulta existente para cliente {codigo_cliente}")
                else:
                    logger.info(f"Registrado erro para cliente {codigo_cliente}: {error_msg}")
        
        except Exception as registro_erro:
            logger.error(f"Erro ao registrar erro do cliente {codigo_cliente}: {str(registro_erro)}")
        
        return None, error_msg

def processar_consulta_completa(execucao_id):
    """Função que executa todo o processamento em background"""
    try:
        execucao = ConsultaExecucao.objects.get(id=execucao_id)
        execucao.atualizar_status('executando', 'Iniciando processamento...')
        
        # 1. Executar consulta SQL
        logger.info(f"Executando consulta SQL para execução {execucao_id}")
        resultados_sql = executar_consulta_sql(
            execucao.credencial_banco, 
            execucao.template_sql,
            execucao.valores_variaveis
        )
        
        execucao.total_registros_sql = len(resultados_sql)
        execucao.save()
        
        if not resultados_sql:
            execucao.atualizar_status('erro', 'Nenhum resultado encontrado na consulta SQL')
            return
        
        # Verifica duplicatas nos resultados SQL
        codigos_clientes = [row.get('codigo_cliente') for row in resultados_sql if row.get('codigo_cliente')]
        codigos_unicos = set(codigos_clientes)
        if len(codigos_clientes) != len(codigos_unicos):
            duplicatas = len(codigos_clientes) - len(codigos_unicos)
            logger.warning(f"Encontradas {duplicatas} duplicatas nos resultados SQL")
            log_buffer = StringIO()
            log_buffer.write(f"⚠️ AVISO: Encontradas {duplicatas} duplicatas nos resultados SQL\n")
            log_buffer.write(f"Total de registros: {len(codigos_clientes)}, Clientes únicos: {len(codigos_unicos)}\n\n")
        else:
            log_buffer = StringIO()
        
        # 2. Inicializar cliente da API
        api_client = HubsoftAPI(execucao.credencial_hubsoft)
        
        # 3. Processar cada cliente
        total_processados = 0
        total_erros = 0
        
        for i, cliente_data in enumerate(resultados_sql, 1):
            # Verifica se a execução foi cancelada
            execucao.refresh_from_db()
            if execucao.status == 'cancelada':
                logger.info(f"Processamento da execução {execucao_id} foi cancelado pelo usuário")
                return
            
            log_buffer.write(f"Processando {i}/{len(resultados_sql)}: {cliente_data.get('codigo_cliente')}\n")
            
            cliente_obj, erro = processar_cliente_api(api_client, cliente_data, execucao)
            
            if cliente_obj:
                total_processados += 1
                log_buffer.write(f"✓ Sucesso: Cliente {cliente_data.get('codigo_cliente')}\n")
            else:
                total_erros += 1
                log_buffer.write(f"✗ Erro: {erro}\n")
            
            # Delay entre requisições
            time.sleep(0.5)
            
            # Atualiza progresso a cada 10 registros
            if i % 10 == 0:
                execucao.total_consultados_api = total_processados
                execucao.total_erros = total_erros
                execucao.log_execucao = log_buffer.getvalue()
                execucao.save()
        
        # Finalizar execução
        execucao.total_consultados_api = total_processados
        execucao.total_erros = total_erros
        execucao.log_execucao = log_buffer.getvalue()
        execucao.atualizar_status('concluida', f'Processamento concluído. {total_processados} sucessos, {total_erros} erros.')
        
        logger.info(f"Processamento da execução {execucao_id} finalizado")
        
    except Exception as e:
        logger.error(f"Erro no processamento da execução {execucao_id}: {e}")
        try:
            execucao = ConsultaExecucao.objects.get(id=execucao_id)
            execucao.atualizar_status('erro', f'Erro durante processamento: {str(e)}')
        except:
            pass

@require_http_methods(["POST"])
def iniciar_processamento(request):
    """Inicia o processamento de uma nova consulta (AJAX-aware)"""
    try:
        titulo = request.POST.get('titulo')
        template_id = request.POST.get('template_sql')
        hubsoft_id = request.POST.get('credencial_hubsoft')
        banco_id = request.POST.get('credencial_banco')

        # --- MUDANÇA 1: Validação retorna JSON de erro ---
        if not all([titulo, template_id, hubsoft_id, banco_id]):
            # Retorna um erro 400 (Bad Request) com uma mensagem JSON
            return JsonResponse({
                'status': 'error',
                'message': 'Todos os campos são obrigatórios.'
            }, status=400)

        # Capturar valores das variáveis
        template_sql = TemplateSQL.objects.get(id=template_id)
        variaveis_config = template_sql.get_variaveis_configuradas()
        valores_variaveis = {}
        
        # Validar e capturar cada variável
        for var_name, config in variaveis_config.items():
            valor = request.POST.get(f'var_{var_name}')
            
            if config.get('obrigatorio', True) and not valor:
                return JsonResponse({
                    'status': 'error',
                    'message': f'A variável "{config.get("label", var_name)}" é obrigatória.'
                }, status=400)
            
            # Usar valor padrão se não fornecido e não obrigatório
            if not valor and not config.get('obrigatorio', True):
                valor = config.get('valor_padrao', '')
            
            valores_variaveis[var_name] = valor

        # Criar nova execução
        execucao = ConsultaExecucao.objects.create(
            titulo=titulo,
            template_sql_id=template_id,
            credencial_hubsoft_id=hubsoft_id,
            credencial_banco_id=banco_id,
            valores_variaveis=valores_variaveis,
            status='pendente'
        )

        # Iniciar processamento em thread separada
        thread = threading.Thread(target=processar_consulta_completa, args=(execucao.id,))
        thread.daemon = True
        thread.start()
        
        # --- MUDANÇA 2: Resposta de sucesso retorna JSON com URL de redirect ---
        # Gera a URL para a página de detalhes da execução
        redirect_url = reverse('detalhe_execucao', args=[execucao.id])

        return JsonResponse({
            'status': 'success',
            'message': f'Processamento "{execucao.titulo}" iniciado com sucesso!',
            'redirect_url': redirect_url # Informa ao frontend para onde ir
        })

    except Exception as e:
        logger.error(f"Erro ao iniciar processamento: {e}")
        # --- MUDANÇA 3: Exceção geral retorna JSON de erro ---
        # Retorna um erro 500 (Internal Server Error) com uma mensagem JSON
        return JsonResponse({
            'status': 'error',
            'message': f'Ocorreu um erro interno no servidor: {str(e)}'
        }, status=500)
    
def listar_execucoes(request):
    """Lista todas as execuções"""
    execucoes = ConsultaExecucao.objects.all().order_by('-data_inicio')
    paginator = Paginator(execucoes, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'campanhas/listar_execucoes.html', {'page_obj': page_obj})

def detalhe_execucao(request, execucao_id):
    """Mostra detalhes de uma execução específica"""
    execucao = get_object_or_404(ConsultaExecucao, id=execucao_id)
    consultas_clientes = ConsultaCliente.objects.filter(execucao=execucao).order_by('-data_consulta')
    
    # Paginação das consultas
    paginator = Paginator(consultas_clientes, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Busca informações do último envio HSM (se existir)
    ultimo_envio_hsm = None
    if execucao.status == 'concluida':
        ultimo_envio_hsm = EnvioHSMMatrix.objects.filter(
            consulta_execucao=execucao
        ).order_by('-data_criacao').first()
    
    context = {
        'execucao': execucao,
        'page_obj': page_obj,
        'total_consultas': consultas_clientes.count(),
        'ultimo_envio_hsm': ultimo_envio_hsm
    }
    
    return render(request, 'campanhas/detalhe_execucao.html', context)

def status_execucao_ajax(request, execucao_id):
    """Retorna o status atual de uma execução via AJAX"""
    try:
        execucao = ConsultaExecucao.objects.get(id=execucao_id)
        return JsonResponse({
            'status': execucao.status,
            'total_registros_sql': execucao.total_registros_sql,
            'total_consultados_api': execucao.total_consultados_api,
            'total_erros': execucao.total_erros,
            'log_execucao': execucao.log_execucao or '',
            'data_fim': execucao.data_fim.isoformat() if execucao.data_fim else None
        })
    except ConsultaExecucao.DoesNotExist:
        return JsonResponse({'error': 'Execução não encontrada'}, status=404)

def exportar_resultados_csv(request, execucao_id):
    """Exporta os resultados de uma execução para CSV"""
    execucao = get_object_or_404(ConsultaExecucao, id=execucao_id)
    
    # Verifica se deve incluir erros
    incluir_erros = request.GET.get('incluir_erros', 'false').lower() == 'true'
    
    if incluir_erros:
        # Exporta todos os registros (sucessos e erros)
        consultas = ConsultaCliente.objects.filter(execucao=execucao)
        filename_suffix = "completo"
    else:
        # Exporta apenas sucessos (comportamento padrão)
        consultas = ConsultaCliente.objects.filter(execucao=execucao, sucesso_api=True)
        filename_suffix = "sucessos"
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="resultados_{filename_suffix}_{execucao.titulo}_{execucao.id}.csv"'
    
    # Criar DataFrame com os resultados
    dados = []
    for consulta in consultas:
        cliente = consulta.cliente
        
        if consulta.sucesso_api:
            # Dados de sucesso
            dados.append({
                'Status': 'Sucesso',
                'Codigo_Cliente': cliente.codigo_cliente,
                'Telefone': cliente.telefone_corrigido or '',
                'Nome': cliente.nome_razaosocial,
                'ID_Fatura': cliente.id_fatura or '',
                'Valor_Fatura': cliente.valor_fatura or '',
                'Data_Vencimento': cliente.vencimento_fatura or '',
                'Codigo_Barras': cliente.codigo_barras or '',
                'PIX_Copia_Cola': cliente.pix or '',
                'Link_Boleto': cliente.link_boleto or '',
                'Erro': '',
                'Data_Consulta': consulta.data_consulta.strftime('%d/%m/%Y %H:%M:%S')
            })
        else:
            # Dados de erro
            dados.append({
                'Status': 'Erro',
                'Codigo_Cliente': cliente.codigo_cliente,
                'Telefone': cliente.telefone_corrigido or '',
                'Nome': cliente.nome_razaosocial,
                'ID_Fatura': cliente.id_fatura or '',
                'Valor_Fatura': '',
                'Data_Vencimento': '',
                'Codigo_Barras': '',
                'PIX_Copia_Cola': '',
                'Link_Boleto': '',
                'Erro': consulta.erro_api or 'Erro não especificado',
                'Data_Consulta': consulta.data_consulta.strftime('%d/%m/%Y %H:%M:%S')
            })
    
    if dados:
        df = pd.DataFrame(dados)
        df.to_csv(response, index=False, encoding='utf-8')
    
    return response

def exportar_erros_csv(request, execucao_id):
    """Exporta apenas os erros de uma execução para CSV"""
    execucao = get_object_or_404(ConsultaExecucao, id=execucao_id)
    consultas_erro = ConsultaCliente.objects.filter(execucao=execucao, sucesso_api=False)
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="erros_{execucao.titulo}_{execucao.id}.csv"'
    
    # Criar DataFrame com os erros
    dados = []
    for consulta in consultas_erro:
        cliente = consulta.cliente
        dados.append({
            'Codigo_Cliente': cliente.codigo_cliente,
            'Nome': cliente.nome_razaosocial,
            'Telefone': cliente.telefone_corrigido or '',
            'ID_Fatura': cliente.id_fatura or '',
            'Erro': consulta.erro_api or 'Erro não especificado',
            'Data_Consulta': consulta.data_consulta.strftime('%d/%m/%Y %H:%M:%S'),
            'Dados_SQL_Originais': str(consulta.dados_originais_sql) if consulta.dados_originais_sql else ''
        })
    
    if dados:
        df = pd.DataFrame(dados)
        df.to_csv(response, index=False, encoding='utf-8')
    
    return response

@require_http_methods(["POST"])
def cancelar_processamento(request, execucao_id):
    """Cancela uma execução em andamento"""
    try:
        execucao = ConsultaExecucao.objects.get(id=execucao_id)
        
        if execucao.status not in ['pendente', 'executando']:
            return JsonResponse({
                'status': 'error',
                'message': 'Apenas execuções pendentes ou em andamento podem ser canceladas.'
            }, status=400)
        
        # Atualiza o log para indicar o cancelamento
        log_atual = execucao.log_execucao or ''
        timestamp = timezone.now().strftime('%d/%m/%Y %H:%M:%S')
        log_cancelamento = f"\n[{timestamp}] ⚠️ PROCESSAMENTO CANCELADO PELO USUÁRIO\n"
        
        execucao.status = 'cancelada'
        execucao.data_fim = timezone.now()
        execucao.erro = 'Processamento cancelado pelo usuário.'
        execucao.log_execucao = log_atual + log_cancelamento
        execucao.save()
        
        logger.info(f"Execução {execucao_id} cancelada pelo usuário")
        
        return JsonResponse({
            'status': 'success',
            'message': 'Processamento cancelado com sucesso.'
        })
        
    except ConsultaExecucao.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Execução não encontrada.'
        }, status=404)
    except Exception as e:
        logger.error(f"Erro ao cancelar execução {execucao_id}: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'Erro ao cancelar processamento: {str(e)}'
        }, status=500)

@require_http_methods(["POST"])
def reiniciar_processamento(request, execucao_id):
    """Reinicia uma execução finalizada resetando seus dados"""
    try:
        execucao = ConsultaExecucao.objects.get(id=execucao_id)
        
        if execucao.status not in ['concluida', 'erro', 'cancelada']:
            return JsonResponse({
                'status': 'error',
                'message': 'Apenas execuções finalizadas podem ser reiniciadas.'
            }, status=400)
        
        # Remove todas as consultas de clientes relacionadas a esta execução
        ConsultaCliente.objects.filter(execucao=execucao).delete()
        
        # Reseta os dados da execução para o estado inicial
        execucao.status = 'pendente'
        execucao.data_fim = None
        execucao.erro = None
        execucao.total_registros_sql = 0
        execucao.total_consultados_api = 0
        execucao.total_erros = 0
        execucao.log_execucao = ''
        execucao.data_inicio = timezone.now()  # Atualiza para o momento do reinício
        execucao.save()
        
        # Inicia o processamento em thread separada
        thread = threading.Thread(target=processar_consulta_completa, args=(execucao.id,))
        thread.daemon = True
        thread.start()
        
        logger.info(f"Execução {execucao_id} reiniciada (dados resetados)")
        
        return JsonResponse({
            'status': 'success',
            'message': 'Processamento reiniciado com sucesso.',
            'redirect_url': reverse('detalhe_execucao', args=[execucao.id])
        })
        
    except ConsultaExecucao.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Execução não encontrada.'
        }, status=404)
    except Exception as e:
        logger.error(f"Erro ao reiniciar execução {execucao_id}: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'Erro ao reiniciar processamento: {str(e)}'
        }, status=500)

def detalhes_cliente(request, cliente_id):
    """Exibe todos os detalhes de um cliente processado"""
    try:
        cliente = ClienteConsultado.objects.get(id=cliente_id)
        consultas = ConsultaCliente.objects.filter(cliente=cliente).select_related('execucao').order_by('-data_consulta')
        
        # Prepara os dados do cliente para exibição
        dados_cliente = {
            'codigo_cliente': cliente.codigo_cliente,
            'nome_razaosocial': cliente.nome_razaosocial,
            'telefone_corrigido': cliente.telefone_corrigido,
            'id_fatura': cliente.id_fatura,
            'vencimento_fatura': cliente.vencimento_fatura,
            'valor_fatura': cliente.valor_fatura,
            'pix': cliente.pix,
            'codigo_barras': cliente.codigo_barras,
            'link_boleto': cliente.link_boleto,
            'data_criacao': cliente.data_criacao,
            'data_atualizacao': cliente.data_atualizacao
        }
        
        context = {
            'cliente': cliente,
            'dados_cliente': dados_cliente,
            'consultas': consultas,
        }
        
        return render(request, 'campanhas/detalhes_cliente.html', context)
        
    except ClienteConsultado.DoesNotExist:
        messages.error(request, 'Cliente não encontrado')
        return redirect('listar_execucoes')

# =============================================================================
# VIEWS PARA ENVIO HSM VIA MATRIX
# =============================================================================

def configurar_envio_hsm(request, execucao_id):
    """Página para configurar o envio de HSM para uma execução"""
    execucao = get_object_or_404(ConsultaExecucao, id=execucao_id)
    
    # Verifica se a execução foi concluída com sucesso
    if execucao.status != 'concluida':
        messages.error(request, 'Apenas execuções concluídas podem ter HSM enviado.')
        return redirect('detalhe_execucao', execucao_id=execucao_id)
    
    # Busca clientes com sucesso na API
    clientes_sucesso = ConsultaCliente.objects.filter(
        execucao=execucao, 
        sucesso_api=True
    ).count()
    
    if clientes_sucesso == 0:
        messages.error(request, 'Nenhum cliente com dados válidos encontrado nesta execução.')
        return redirect('detalhe_execucao', execucao_id=execucao_id)
    
    # Busca configurações e templates disponíveis
    matrix_configs = MatrixAPIConfig.objects.filter(ativo=True)
    hsm_templates = HSMTemplate.objects.filter(ativo=True)
    
    context = {
        'execucao': execucao,
        'clientes_sucesso': clientes_sucesso,
        'matrix_configs': matrix_configs,
        'hsm_templates': hsm_templates
    }
    
    return render(request, 'campanhas/configurar_envio_hsm.html', context)

def obter_variaveis_hsm_template(request, template_id):
    """Retorna as variáveis de um template HSM específico via AJAX"""
    try:
        template = HSMTemplate.objects.get(id=template_id, ativo=True)
        variaveis = template.get_variaveis_descricao()
        
        return JsonResponse({
            'status': 'success',
            'variaveis': variaveis,
            'template_nome': template.nome,
            'hsm_id': template.hsm_id,
            'cod_flow': template.cod_flow,
            'tipo_envio': template.tipo_envio
        })
    except HSMTemplate.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Template HSM não encontrado'
        }, status=404)
    except Exception as e:
        logger.error(f"Erro ao obter variáveis do template HSM {template_id}: {e}")
        return JsonResponse({
            'status': 'error',
            'message': f'Erro interno: {str(e)}'
        }, status=500)

def serializar_valor_para_json(valor):
    """Converte valores para tipos serializáveis em JSON"""
    if valor is None:
        return ''
    
    # Se é um objeto date ou datetime, converte para string
    if hasattr(valor, 'strftime'):
        if hasattr(valor, 'hour'):  # datetime
            return valor.strftime('%d/%m/%Y %H:%M')
        else:  # date
            return valor.strftime('%d/%m/%Y')
    
    # Converte outros tipos para string
    return str(valor) if valor else ''

def mapear_campos_cliente_para_hsm(cliente_data):
    """Mapeia os campos do cliente para variáveis do HSM"""
    
    # Mapeamento padrão dos campos do cliente com serialização segura
    mapeamento = {
        'nome_cliente': serializar_valor_para_json(cliente_data.get('nome_razaosocial')),
        'codigo_cliente': serializar_valor_para_json(cliente_data.get('codigo_cliente')),
        'telefone': serializar_valor_para_json(cliente_data.get('telefone_corrigido')),
        'valor_fatura': serializar_valor_para_json(cliente_data.get('valor_fatura')),
        'vencimento_fatura': serializar_valor_para_json(cliente_data.get('vencimento_fatura')),
        'codigo_barras': serializar_valor_para_json(cliente_data.get('codigo_barras')),
        'pix_copia_cola': serializar_valor_para_json(cliente_data.get('pix')),
        'link_boleto': serializar_valor_para_json(cliente_data.get('link_boleto')),
        'id_fatura': serializar_valor_para_json(cliente_data.get('id_fatura'))
    }
    
    return mapeamento

def verificar_variaveis_vazias(variaveis_hsm, configuracao_variaveis, dados_cliente):
    """
    Verifica se alguma variável necessária está vazia nos dados do cliente
    
    Args:
        variaveis_hsm: Dict com variáveis preparadas para envio
        configuracao_variaveis: Mapeamento de variáveis HSM -> campos cliente
        dados_cliente: Dados do cliente para verificação
    
    Returns:
        bool: True se alguma variável obrigatória estiver vazia
    """
    for var_hsm, campo_cliente in configuracao_variaveis.items():
        valor = dados_cliente.get(campo_cliente, '')
        # Considera vazio se for None, string vazia ou só espaços
        if not valor or (isinstance(valor, str) and not valor.strip()):
            logger.info(f"Variável {var_hsm} (campo {campo_cliente}) está vazia para cliente {dados_cliente.get('codigo_cliente')}")
            return True
    return False

def enviar_hsm_matrix_django(matrix_config, hsm_template, cliente, variaveis_hsm):
    """
    Função para envio de HSM via API Matrix integrada ao Django
    
    Args:
        matrix_config: Objeto MatrixAPIConfig com configurações da API
        hsm_template: Objeto HSMTemplate com dados do template
        cliente: Objeto ClienteConsultado com dados do cliente
        variaveis_hsm: Dict com variáveis para substituição no HSM
    
    Returns:
        dict: Resultado da operação com success, error, status_code, data
    """
    try:
        # Configuração da API
        base_url = matrix_config.base_url.rstrip('/')
        headers = {
            'Authorization': matrix_config.api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # Criação do contato
        contato = {
            "nome": cliente.nome_razaosocial or "Cliente",
            "telefone": cliente.telefone_corrigido or ""
        }
        
        # Construção do payload
        payload = {
            "cod_conta": matrix_config.cod_conta,
            "hsm": hsm_template.hsm_id,
            "tipo_envio": hsm_template.tipo_envio or 1,  # Default: atendimento automático
            "cod_flow": hsm_template.cod_flow or 0,
            "start_flow": 1,  # Inicia flow automaticamente
            "contato": contato,
            "bol_incluir_atual": 1  # Inclui mesmo com atendimento em andamento
        }
        
        # Adiciona variáveis se fornecidas (garantindo serialização)
        if variaveis_hsm:
            variaveis_serializadas = {}
            for chave, valor in variaveis_hsm.items():
                variaveis_serializadas[str(chave)] = serializar_valor_para_json(valor)
            payload["variaveis"] = variaveis_serializadas
        
        # URL do endpoint
        url = f"{base_url}/rest/v1/sendHsm"
        
        logger.info(f"Enviando HSM para {cliente.codigo_cliente} - {cliente.nome_razaosocial}")
        logger.debug(f"URL: {url}, Payload: {payload}")
        
        # Executa a requisição
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        # Retorna sucesso
        return {
            "success": True,
            "status_code": response.status_code,
            "data": response.json(),
            "error": None
        }
        
    except requests.exceptions.Timeout:
        logger.error(f"Timeout ao enviar HSM para {cliente.codigo_cliente}")
        return {
            "success": False,
            "error": "Timeout na requisição - servidor não respondeu em 30 segundos",
            "status_code": None,
            "data": None
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro de requisição ao enviar HSM para {cliente.codigo_cliente}: {e}")
        return {
            "success": False,
            "error": f"Erro de rede: {str(e)}",
            "status_code": getattr(response, 'status_code', None),
            "data": getattr(response, 'text', None)
        }
        
    except Exception as e:
        logger.error(f"Erro inesperado ao enviar HSM para {cliente.codigo_cliente}: {e}")
        return {
            "success": False,
            "error": f"Erro inesperado: {str(e)}",
            "status_code": None,
            "data": None
        }

def processar_envio_hsm_background(envio_matrix_id):
    """Processa o envio de HSM em background"""
    
    try:
        envio_matrix = EnvioHSMMatrix.objects.get(id=envio_matrix_id)
        envio_matrix.atualizar_status('enviando', 'Iniciando envio de HSM...')
        
        # Busca clientes da execução com sucesso na API
        consultas_sucesso = ConsultaCliente.objects.filter(
            execucao=envio_matrix.consulta_execucao,
            sucesso_api=True
        ).select_related('cliente')
        
        total_clientes = consultas_sucesso.count()
        envio_matrix.total_clientes = total_clientes
        envio_matrix.save()
        
        if total_clientes == 0:
            envio_matrix.atualizar_status('erro', 'Nenhum cliente com dados válidos encontrado.')
            return
        
        # Cria registros individuais de envio
        envios_individuais = []
        for consulta in consultas_sucesso:
            cliente = consulta.cliente
            
            # Mapeia campos do cliente para variáveis HSM
            dados_cliente = {
                'nome_razaosocial': cliente.nome_razaosocial,
                'codigo_cliente': cliente.codigo_cliente,
                'telefone_corrigido': cliente.telefone_corrigido,
                'valor_fatura': cliente.valor_fatura,
                'vencimento_fatura': cliente.vencimento_fatura,
                'codigo_barras': cliente.codigo_barras,
                'pix': cliente.pix,
                'link_boleto': cliente.link_boleto,
                'id_fatura': cliente.id_fatura
            }
            
            variaveis_cliente = mapear_campos_cliente_para_hsm(dados_cliente)
            
            envio_individual = EnvioHSMIndividual(
                envio_matrix=envio_matrix,
                cliente=cliente,
                variaveis_utilizadas=variaveis_cliente,
                status='pendente'
            )
            envios_individuais.append(envio_individual)
        
        # Salva todos os envios individuais
        EnvioHSMIndividual.objects.bulk_create(envios_individuais)
        
        # Processa cada envio individual
        total_enviados = 0
        total_erros = 0
        
        matrix_config = envio_matrix.matrix_api_config
        template_hsm = envio_matrix.hsm_template
        
        for envio_individual in EnvioHSMIndividual.objects.filter(envio_matrix=envio_matrix):
            # Verifica se o envio foi cancelado
            envio_matrix.refresh_from_db()
            if envio_matrix.status_envio == 'cancelado':
                logger.info(f"Envio HSM {envio_matrix_id} foi cancelado pelo usuário")
                break
            
            envio_individual.status = 'enviando'
            envio_individual.save()
            
            try:
                cliente = envio_individual.cliente
                
                # Determina qual template usar baseado na disponibilidade das variáveis
                usar_contingencia = False
                template_a_usar = template_hsm
                configuracao_a_usar = envio_matrix.configuracao_variaveis
                
                # Primeiro, verifica se o template principal tem todas as variáveis
                if envio_matrix.configuracao_variaveis:
                    # Verifica se alguma variável do template principal está vazia
                    if verificar_variaveis_vazias(None, envio_matrix.configuracao_variaveis, envio_individual.variaveis_utilizadas):
                        # Se tem template de contingência, usa ele
                        if envio_matrix.hsm_template_contingencia and envio_matrix.configuracao_variaveis_contingencia:
                            usar_contingencia = True
                            template_a_usar = envio_matrix.hsm_template_contingencia
                            configuracao_a_usar = envio_matrix.configuracao_variaveis_contingencia
                            logger.info(f"Usando template de contingência para cliente {cliente.codigo_cliente} - variáveis principais vazias")
                        else:
                            # Não tem contingência, mas vamos tentar enviar mesmo assim
                            logger.warning(f"Variáveis vazias para cliente {cliente.codigo_cliente} mas não há template de contingência configurado")
                
                # Prepara variáveis baseadas na configuração escolhida
                variaveis_hsm = {}
                if configuracao_a_usar:
                    for var_hsm, campo_cliente in configuracao_a_usar.items():
                        valor = envio_individual.variaveis_utilizadas.get(campo_cliente, '')
                        variaveis_hsm[var_hsm] = str(valor)
                
                # Registra qual template está sendo usado
                envio_individual.template_usado = 'contingencia' if usar_contingencia else 'principal'
                envio_individual.save()
                
                # Envia HSM usando a função integrada do Django
                resultado = enviar_hsm_matrix_django(
                    matrix_config=matrix_config,
                    hsm_template=template_a_usar,
                    cliente=cliente,
                    variaveis_hsm=variaveis_hsm
                )
                
                if resultado['success']:
                    envio_individual.marcar_enviado(resultado.get('data'))
                    total_enviados += 1
                    logger.info(f"HSM enviado com sucesso para {cliente.codigo_cliente}")
                else:
                    erro_msg = resultado.get('error', 'Erro desconhecido')
                    envio_individual.marcar_erro(erro_msg, resultado.get('data'))
                    total_erros += 1
                    logger.error(f"Erro ao enviar HSM para {cliente.codigo_cliente}: {erro_msg}")
                
            except Exception as e:
                erro_msg = f"Erro inesperado: {str(e)}"
                envio_individual.marcar_erro(erro_msg)
                total_erros += 1
                logger.error(f"Erro inesperado ao enviar HSM para {envio_individual.cliente.codigo_cliente}: {e}")
            
            # Delay entre envios
            time.sleep(1)
            
            # Atualiza progresso a cada 5 envios
            if (total_enviados + total_erros) % 5 == 0:
                envio_matrix.total_enviados = total_enviados
                envio_matrix.total_erros = total_erros
                envio_matrix.total_pendentes = total_clientes - total_enviados - total_erros
                envio_matrix.save()
        
        # Finaliza o envio
        envio_matrix.total_enviados = total_enviados
        envio_matrix.total_erros = total_erros
        envio_matrix.total_pendentes = total_clientes - total_enviados - total_erros
        
        if envio_matrix.status_envio != 'cancelado':
            status_final = 'concluido' if total_erros == 0 else 'concluido'
            log_final = f'Envio concluído. {total_enviados} enviados, {total_erros} erros.'
            envio_matrix.atualizar_status(status_final, log_final)
        
        logger.info(f"Processamento do envio HSM {envio_matrix_id} finalizado")
        
    except Exception as e:
        logger.error(f"Erro no processamento do envio HSM {envio_matrix_id}: {e}")
        try:
            envio_matrix = EnvioHSMMatrix.objects.get(id=envio_matrix_id)
            envio_matrix.atualizar_status('erro', f'Erro durante envio: {str(e)}')
        except:
            pass

def obter_ultimo_envio_hsm(execucao_id):
    """Obtém o último envio HSM de uma execução para reutilizar configurações"""
    try:
        ultimo_envio = EnvioHSMMatrix.objects.filter(
            consulta_execucao_id=execucao_id
        ).order_by('-data_criacao').first()
        
        if ultimo_envio:
            return {
                'matrix_config': ultimo_envio.matrix_api_config,
                'hsm_template': ultimo_envio.hsm_template,
                'hsm_template_contingencia': ultimo_envio.hsm_template_contingencia,
                'configuracao_variaveis': ultimo_envio.configuracao_variaveis,
                'configuracao_variaveis_contingencia': ultimo_envio.configuracao_variaveis_contingencia
            }
    except Exception as e:
        logger.error(f"Erro ao obter último envio HSM da execução {execucao_id}: {e}")
    
    return None

@require_http_methods(["POST"])
def enviar_hsm_configuracao_atual(request, execucao_id):
    """Envia HSM usando as configurações do último envio da execução"""
    try:
        titulo = request.POST.get('titulo')
        
        if not titulo:
            return JsonResponse({
                'status': 'error',
                'message': 'Título do envio é obrigatório.'
            }, status=400)
        
        # Busca execução
        execucao = ConsultaExecucao.objects.get(id=execucao_id)
        
        # Verifica se a execução foi concluída com sucesso
        if execucao.status != 'concluida':
            return JsonResponse({
                'status': 'error',
                'message': 'Apenas execuções concluídas podem ter HSM enviado.'
            }, status=400)
        
        # Obtém configurações do último envio
        config_anterior = obter_ultimo_envio_hsm(execucao_id)
        
        if not config_anterior:
            return JsonResponse({
                'status': 'error',
                'message': 'Nenhum envio HSM anterior encontrado para esta execução. Use a configuração manual.'
            }, status=404)
        
        # Verifica se ainda há clientes com dados válidos
        clientes_sucesso = ConsultaCliente.objects.filter(
            execucao=execucao, 
            sucesso_api=True
        ).count()
        
        if clientes_sucesso == 0:
            return JsonResponse({
                'status': 'error',
                'message': 'Nenhum cliente com dados válidos encontrado nesta execução.'
            }, status=400)
        
        # Cria novo envio HSM com as configurações anteriores
        envio_matrix = EnvioHSMMatrix.objects.create(
            titulo=titulo,
            hsm_template=config_anterior['hsm_template'],
            hsm_template_contingencia=config_anterior['hsm_template_contingencia'],
            matrix_api_config=config_anterior['matrix_config'],
            consulta_execucao=execucao,
            configuracao_variaveis=config_anterior['configuracao_variaveis'],
            configuracao_variaveis_contingencia=config_anterior['configuracao_variaveis_contingencia'],
            status_envio='pendente'
        )
        
        # Inicia processamento em thread separada
        thread = threading.Thread(target=processar_envio_hsm_background, args=(envio_matrix.id,))
        thread.daemon = True
        thread.start()
        
        redirect_url = reverse('detalhe_envio_hsm', args=[envio_matrix.id])
        
        return JsonResponse({
            'status': 'success',
            'message': f'Envio HSM "{envio_matrix.titulo}" iniciado com as configurações anteriores!',
            'redirect_url': redirect_url
        })
        
    except ConsultaExecucao.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Execução não encontrada.'
        }, status=404)
    except Exception as e:
        logger.error(f"Erro ao iniciar envio HSM com configuração atual: {e}")
        return JsonResponse({
            'status': 'error',
            'message': f'Erro interno: {str(e)}'
        }, status=500)

@require_http_methods(["POST"])
def iniciar_envio_hsm(request):
    """Inicia o envio de HSM para uma execução"""
    try:
        titulo = request.POST.get('titulo')
        execucao_id = request.POST.get('execucao_id')
        hsm_template_id = request.POST.get('hsm_template')
        matrix_config_id = request.POST.get('matrix_config')
        
        # Validação
        if not all([titulo, execucao_id, hsm_template_id, matrix_config_id]):
            return JsonResponse({
                'status': 'error',
                'message': 'Todos os campos são obrigatórios.'
            }, status=400)
        
        # Busca objetos relacionados
        execucao = ConsultaExecucao.objects.get(id=execucao_id)
        hsm_template = HSMTemplate.objects.get(id=hsm_template_id)
        matrix_config = MatrixAPIConfig.objects.get(id=matrix_config_id)
        
        # Captura configuração das variáveis (mapeamento HSM -> Campo Cliente)
        configuracao_variaveis = {}
        variaveis_hsm = hsm_template.get_variaveis_descricao()
        
        for var_hsm in variaveis_hsm.keys():
            campo_mapeado = request.POST.get(f'var_mapping_{var_hsm}')
            if campo_mapeado:
                configuracao_variaveis[var_hsm] = campo_mapeado
        
        # Verifica se há template de contingência
        hsm_template_contingencia_id = request.POST.get('hsm_template_contingencia')
        hsm_template_contingencia = None
        configuracao_variaveis_contingencia = {}
        
        if hsm_template_contingencia_id:
            hsm_template_contingencia = HSMTemplate.objects.get(id=hsm_template_contingencia_id)
            variaveis_hsm_contingencia = hsm_template_contingencia.get_variaveis_descricao()
            
            for var_hsm in variaveis_hsm_contingencia.keys():
                campo_mapeado = request.POST.get(f'var_mapping_contingencia_{var_hsm}')
                if campo_mapeado:
                    configuracao_variaveis_contingencia[var_hsm] = campo_mapeado
        
        # Cria novo envio HSM
        envio_matrix = EnvioHSMMatrix.objects.create(
            titulo=titulo,
            hsm_template=hsm_template,
            hsm_template_contingencia=hsm_template_contingencia,
            matrix_api_config=matrix_config,
            consulta_execucao=execucao,
            configuracao_variaveis=configuracao_variaveis,
            configuracao_variaveis_contingencia=configuracao_variaveis_contingencia,
            status_envio='pendente'
        )
        
        # Inicia processamento em thread separada
        thread = threading.Thread(target=processar_envio_hsm_background, args=(envio_matrix.id,))
        thread.daemon = True
        thread.start()
        
        redirect_url = reverse('detalhe_envio_hsm', args=[envio_matrix.id])
        
        return JsonResponse({
            'status': 'success',
            'message': f'Envio HSM "{envio_matrix.titulo}" iniciado com sucesso!',
            'redirect_url': redirect_url
        })
        
    except Exception as e:
        logger.error(f"Erro ao iniciar envio HSM: {e}")
        return JsonResponse({
            'status': 'error',
            'message': f'Erro interno: {str(e)}'
        }, status=500)

def listar_envios_hsm(request):
    """Lista todos os envios HSM"""
    envios = EnvioHSMMatrix.objects.all().order_by('-data_criacao')
    paginator = Paginator(envios, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'campanhas/listar_envios_hsm.html', {'page_obj': page_obj})

def detalhe_envio_hsm(request, envio_id):
    """Mostra detalhes de um envio HSM específico"""
    envio = get_object_or_404(EnvioHSMMatrix, id=envio_id)
    envios_individuais = EnvioHSMIndividual.objects.filter(envio_matrix=envio).order_by('-data_envio')
    
    # Paginação dos envios individuais
    paginator = Paginator(envios_individuais, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'envio': envio,
        'page_obj': page_obj,
        'total_envios': envios_individuais.count()
    }
    
    return render(request, 'campanhas/detalhe_envio_hsm.html', context)

def status_envio_hsm_ajax(request, envio_id):
    """Retorna o status atual de um envio HSM via AJAX"""
    try:
        envio = EnvioHSMMatrix.objects.get(id=envio_id)
        return JsonResponse({
            'status': envio.status_envio,
            'total_clientes': envio.total_clientes,
            'total_enviados': envio.total_enviados,
            'total_erros': envio.total_erros,
            'total_pendentes': envio.total_pendentes,
            'progresso_percentual': envio.get_progresso_percentual(),
            'log_execucao': envio.log_execucao or '',
            'data_fim_envio': envio.data_fim_envio.isoformat() if envio.data_fim_envio else None
        })
    except EnvioHSMMatrix.DoesNotExist:
        return JsonResponse({'error': 'Envio não encontrado'}, status=404)

@require_http_methods(["POST"])
def cancelar_envio_hsm(request, envio_id):
    """Cancela um envio HSM em andamento"""
    try:
        envio = EnvioHSMMatrix.objects.get(id=envio_id)
        
        if envio.status_envio not in ['pendente', 'enviando']:
            return JsonResponse({
                'status': 'error',
                'message': 'Apenas envios pendentes ou em andamento podem ser cancelados.'
            }, status=400)
        
        envio.atualizar_status('cancelado', 'Envio cancelado pelo usuário')
        
        # Cancela envios individuais pendentes
        EnvioHSMIndividual.objects.filter(
            envio_matrix=envio,
            status='pendente'
        ).update(status='cancelado')
        
        logger.info(f"Envio HSM {envio_id} cancelado pelo usuário")
        
        return JsonResponse({
            'status': 'success',
            'message': 'Envio cancelado com sucesso.'
        })
        
    except EnvioHSMMatrix.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Envio não encontrado.'
        }, status=404)
    except Exception as e:
        logger.error(f"Erro ao cancelar envio HSM {envio_id}: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'Erro ao cancelar envio: {str(e)}'
        }, status=500)