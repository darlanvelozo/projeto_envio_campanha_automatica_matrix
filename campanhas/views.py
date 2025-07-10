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
    ConsultaExecucao, ClienteConsultado, ConsultaCliente
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

def executar_consulta_sql(credencial_banco, query):
    """Executa uma consulta SQL no banco especificado"""
    try:
        # Limpa a query de possíveis problemas de formatação
        query = query.strip()
        # Remove múltiplos espaços em branco
        query = ' '.join(query.split())
        
        logger.info(f"Executando consulta SQL com credencial: {credencial_banco.titulo}")
        logger.info(f"Query SQL: {query}")
        
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
    
    try:
        # Consulta a API
        dados_cliente = api_client.consultar_cliente_financeiro(codigo_cliente)
        
        if not dados_cliente:
            return None, "Falha ao consultar dados na API"
        
        # Busca a fatura específica
        fatura = obter_fatura_por_id(dados_cliente, id_fatura_desejada)
        
        if not fatura:
            return None, f"Fatura {id_fatura_desejada} não encontrada"
        
        # Cria ou atualiza o cliente consultado
        cliente_obj, created = ClienteConsultado.objects.get_or_create(
            codigo_cliente=codigo_cliente,
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
        
        # Registra a consulta
        ConsultaCliente.objects.create(
            execucao=execucao,
            cliente=cliente_obj,
            dados_originais_sql=cliente_data,
            dados_api_response=dados_cliente,
            sucesso_api=True
        )
        
        return cliente_obj, None
        
    except Exception as e:
        error_msg = f"Erro ao processar cliente {codigo_cliente}: {str(e)}"
        logger.error(error_msg)
        
        # Registra o erro
        if codigo_cliente:
            cliente_obj, _ = ClienteConsultado.objects.get_or_create(
                codigo_cliente=codigo_cliente,
                defaults={
                    'nome_razaosocial': cliente_data.get('nome_razaosocial', ''),
                    'data_criacao': timezone.now()
                }
            )
            
            ConsultaCliente.objects.create(
                execucao=execucao,
                cliente=cliente_obj,
                dados_originais_sql=cliente_data,
                sucesso_api=False,
                erro_api=error_msg
            )
        
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
            execucao.template_sql.consulta_sql
        )
        
        execucao.total_registros_sql = len(resultados_sql)
        execucao.save()
        
        if not resultados_sql:
            execucao.atualizar_status('erro', 'Nenhum resultado encontrado na consulta SQL')
            return
        
        # 2. Inicializar cliente da API
        api_client = HubsoftAPI(execucao.credencial_hubsoft)
        
        # 3. Processar cada cliente
        total_processados = 0
        total_erros = 0
        log_buffer = StringIO()
        
        for i, cliente_data in enumerate(resultados_sql, 1):
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

        # Criar nova execução
        execucao = ConsultaExecucao.objects.create(
            titulo=titulo,
            template_sql_id=template_id,
            credencial_hubsoft_id=hubsoft_id,
            credencial_banco_id=banco_id,
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
    
    context = {
        'execucao': execucao,
        'page_obj': page_obj,
        'total_consultas': consultas_clientes.count()
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
    consultas = ConsultaCliente.objects.filter(execucao=execucao, sucesso_api=True)
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="resultados_{execucao.titulo}_{execucao.id}.csv"'
    
    # Criar DataFrame com os resultados
    dados = []
    for consulta in consultas:
        cliente = consulta.cliente
        dados.append({
            'Telefone': cliente.telefone_corrigido or '',
            'Nome': cliente.nome_razaosocial,
            'nome_cliente': cliente.nome_razaosocial,
            'valor': cliente.valor_fatura or '',
            'data_vencimento': cliente.vencimento_fatura or '',
            'codigo_barras': cliente.codigo_barras or '',
            'pix_copia_cola': cliente.pix or '',
            'link': cliente.link_boleto or ''
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
        
        execucao.status = 'cancelada'
        execucao.data_fim = timezone.now()
        execucao.erro = 'Processamento cancelado pelo usuário.'
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
    """Reinicia uma execução finalizada"""
    try:
        execucao = ConsultaExecucao.objects.get(id=execucao_id)
        
        if execucao.status not in ['concluida', 'erro', 'cancelada']:
            return JsonResponse({
                'status': 'error',
                'message': 'Apenas execuções finalizadas podem ser reiniciadas.'
            }, status=400)
        
        # Cria uma nova execução com os mesmos parâmetros
        nova_execucao = ConsultaExecucao.objects.create(
            titulo=f"Reinício: {execucao.titulo}",
            template_sql=execucao.template_sql,
            credencial_hubsoft=execucao.credencial_hubsoft,
            credencial_banco=execucao.credencial_banco,
            status='pendente'
        )
        
        # Inicia o processamento em thread separada
        thread = threading.Thread(target=processar_consulta_completa, args=(nova_execucao.id,))
        thread.daemon = True
        thread.start()
        
        logger.info(f"Execução {execucao_id} reiniciada como {nova_execucao.id}")
        
        return JsonResponse({
            'status': 'success',
            'message': 'Processamento reiniciado com sucesso.',
            'redirect_url': reverse('detalhe_execucao', args=[nova_execucao.id])
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