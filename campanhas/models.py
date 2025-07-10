# models.py (versão melhorada)
from django.db import models
from django.core.exceptions import ValidationError
import json
from django.utils import timezone

class TemplateSQL(models.Model):
    consulta_sql = models.TextField(verbose_name="Consulta SQL")
    titulo = models.CharField(max_length=255, verbose_name="Título")
    descricao = models.TextField(blank=True, null=True, verbose_name="Descrição")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    data_criacao = models.DateTimeField(null=True, blank=True, verbose_name="Data de Criação")
    data_atualizacao = models.DateTimeField(null=True, blank=True, verbose_name="Data de Atualização")

    class Meta:
        verbose_name = "Template SQL"
        verbose_name_plural = "Templates SQL"

    def __str__(self):
        return self.titulo

class CredenciaisBancoDados(models.Model):
    TIPO_BANCO_CHOICES = [
        ('mysql', 'MySQL'),
        ('postgresql', 'PostgreSQL'),
        ('sqlserver', 'SQL Server'),
        ('oracle', 'Oracle'),
    ]

    titulo = models.CharField(max_length=100, verbose_name="Título")
    tipo_banco = models.CharField(max_length=20, choices=TIPO_BANCO_CHOICES, verbose_name="Tipo de Banco")
    host = models.CharField(max_length=255, verbose_name="Host")
    porta = models.IntegerField(verbose_name="Porta")
    banco = models.CharField(max_length=100, verbose_name="Nome do Banco")
    usuario = models.CharField(max_length=100, verbose_name="Usuário")
    senha = models.CharField(max_length=100, verbose_name="Senha")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    data_criacao = models.DateTimeField(auto_now_add=True, verbose_name="Data de Criação")
    data_atualizacao = models.DateTimeField(auto_now=True, verbose_name="Data de Atualização")

    class Meta:
        verbose_name = "Credencial de Banco de Dados"
        verbose_name_plural = "Credenciais de Banco de Dados"

    def __str__(self):
        return f"{self.titulo} - {self.tipo_banco} ({self.host})"

    def get_connection_string(self):
        if self.tipo_banco == 'mysql':
            return f"mysql://{self.usuario}:{self.senha}@{self.host}:{self.porta}/{self.banco}"
        elif self.tipo_banco == 'postgresql':
            return f"postgresql://{self.usuario}:{self.senha}@{self.host}:{self.porta}/{self.banco}"
        elif self.tipo_banco == 'sqlserver':
            return f"mssql://{self.usuario}:{self.senha}@{self.host}:{self.porta}/{self.banco}"
        elif self.tipo_banco == 'oracle':
            return f"oracle://{self.usuario}:{self.senha}@{self.host}:{self.porta}/{self.banco}"
        return None

class CredenciaisHubsoft(models.Model):
    titulo = models.CharField(max_length=100, verbose_name="Título")
    client_id = models.CharField(max_length=100, verbose_name="Client ID")
    client_secret = models.CharField(max_length=100, verbose_name="Client Secret")
    username = models.EmailField(verbose_name="Username")
    password = models.CharField(max_length=100, verbose_name="Password")
    url_base = models.URLField(verbose_name="URL Base")
    url_token = models.URLField(verbose_name="URL Token")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    data_criacao = models.DateTimeField(auto_now_add=True, verbose_name="Data de Criação")
    data_atualizacao = models.DateTimeField(auto_now=True, verbose_name="Data de Atualização")

    class Meta:
        verbose_name = "Credencial Hubsoft"
        verbose_name_plural = "Credenciais Hubsoft"

    def __str__(self):
        return f"{self.titulo} - {self.username}"

class ClienteConsultado(models.Model):
    codigo_cliente = models.CharField(max_length=50, verbose_name="Código do Cliente", unique=True)
    nome_razaosocial = models.CharField(max_length=255, verbose_name="Nome/Razão Social")
    telefone_corrigido = models.CharField(max_length=20, verbose_name="Telefone Corrigido", blank=True, null=True)
    id_fatura = models.CharField(max_length=50, verbose_name="ID da Fatura", null=True, blank=True)
    vencimento_fatura = models.DateField(verbose_name="Vencimento da Fatura", null=True, blank=True)
    valor_fatura = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor da Fatura", null=True, blank=True)
    pix = models.CharField(max_length=255, verbose_name="Código PIX", null=True, blank=True)
    codigo_barras = models.CharField(max_length=255, verbose_name="Código de Barras", null=True, blank=True)
    link_boleto = models.URLField(verbose_name="Link do Boleto", null=True, blank=True)
    data_criacao = models.DateTimeField(null=True, blank=True, verbose_name="Data de Criação")
    data_atualizacao = models.DateTimeField(null=True, blank=True, verbose_name="Data de Atualização")

    class Meta:
        verbose_name = "Cliente Consultado"
        verbose_name_plural = "Clientes Consultados"

    def __str__(self):
        return f"{self.codigo_cliente} - {self.nome_razaosocial}"

class ConsultaExecucao(models.Model):
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('executando', 'Executando'),
        ('concluida', 'Concluída'),
        ('cancelada', 'Cancelada'),
        ('erro', 'Erro'),
    ]
    
    titulo = models.CharField(max_length=255, verbose_name="Título da Execução")
    template_sql = models.ForeignKey(TemplateSQL, on_delete=models.CASCADE, verbose_name="Template SQL")
    credencial_hubsoft = models.ForeignKey(CredenciaisHubsoft, on_delete=models.CASCADE, verbose_name="Credencial Hubsoft")
    credencial_banco = models.ForeignKey(CredenciaisBancoDados, on_delete=models.CASCADE, verbose_name="Credencial Banco de Dados")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente', verbose_name="Status")
    total_registros_sql = models.IntegerField(default=0, verbose_name="Total de Registros SQL")
    total_consultados_api = models.IntegerField(default=0, verbose_name="Total Consultados API")
    total_erros = models.IntegerField(default=0, verbose_name="Total de Erros")
    log_execucao = models.TextField(blank=True, null=True, verbose_name="Log de Execução")
    data_inicio = models.DateTimeField(auto_now_add=True, verbose_name="Data de Início")
    data_fim = models.DateTimeField(null=True, blank=True, verbose_name="Data de Fim")

    class Meta:
        verbose_name = "Execução de Consulta"
        verbose_name_plural = "Execuções de Consultas"
        ordering = ['-data_inicio']

    def __str__(self):
        return f"{self.titulo} - {self.status} ({self.data_inicio.strftime('%d/%m/%Y %H:%M')})"

    def atualizar_status(self, status, log=None):
        self.status = status
        if log:
            self.log_execucao = log
        if status in ['concluida', 'erro']:
            self.data_fim = timezone.now()
        self.save()

class ConsultaCliente(models.Model):
    execucao = models.ForeignKey(ConsultaExecucao, on_delete=models.CASCADE, verbose_name="Execução", null=True, blank=True)
    cliente = models.ForeignKey(ClienteConsultado, on_delete=models.CASCADE, verbose_name="Cliente")
    dados_originais_sql = models.JSONField(null=True, blank=True, verbose_name="Dados Originais SQL", help_text="Dados retornados da consulta SQL")
    dados_api_response = models.JSONField(null=True, blank=True, verbose_name="Resposta da API", help_text="Dados retornados da API")
    sucesso_api = models.BooleanField(default=False, verbose_name="Sucesso na API")
    erro_api = models.TextField(blank=True, null=True, verbose_name="Erro da API")
    data_consulta = models.DateTimeField(auto_now_add=True, verbose_name="Data da Consulta")

    class Meta:
        verbose_name = "Consulta de Cliente"
        verbose_name_plural = "Consultas de Clientes"
        ordering = ['-data_consulta']
        unique_together = ['execucao', 'cliente']

    def __str__(self):
        return f"{self.cliente.nome_razaosocial} - {self.execucao.titulo if self.execucao else 'Sem execução'} ({self.data_consulta.strftime('%d/%m/%Y %H:%M')})"

class MatrixAPIConfig(models.Model):
    
    """
    Configurações da API Matrix para envio de HSM
    
    Armazena as configurações de conexão com a API Matrix,
    incluindo URL base e chave de autenticação.
    """
    
    nome = models.CharField(
        max_length=100,
        verbose_name="Nome da Configuração",
        help_text="Nome para identificar esta configuração"
    )
    
    base_url = models.URLField(
        verbose_name="URL Base da API",
        help_text="URL base da API Matrix (ex: https://megalink.matrixdobrasil.ai)"
    )
    
    api_key = models.CharField(
        max_length=255,
        verbose_name="Chave da API",
        help_text="Chave de autenticação da API Matrix"
    )
    
    cod_conta = models.IntegerField(
        verbose_name="Código da Conta",
        help_text="Código da conta na Matrix"
    )
    
    ativo = models.BooleanField(
        default=True,
        verbose_name="Ativo",
        help_text="Se esta configuração está ativa"
    )
    
    data_criacao = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Data de Criação"
    )
    
    data_atualizacao = models.DateTimeField(
        auto_now=True,
        verbose_name="Data de Atualização"
    )
    
    class Meta:
        verbose_name = "Configuração da API Matrix"
        verbose_name_plural = "Configurações da API Matrix"
        ordering = ['-ativo', 'nome']
    
    def __str__(self):
        return f"{self.nome} - {self.base_url}"
    
    def get_config_dict(self):
        """Retorna configuração como dicionário"""
        return {
            'base_url': self.base_url,
            'api_key': self.api_key,
            'cod_conta': self.cod_conta
        }
    
class HSMTemplate(models.Model):
    """
    Templates de HSM para envio
    
    Armazena os templates de mensagens HSM com suas configurações
    e variáveis necessárias.
    """
    
    TIPO_ENVIO_CHOICES = [
        (1, 'Atendimento Automático'),
        (2, 'Notificação'),
        (3, 'Fila de Atendimento'),
    ]
    
    nome = models.CharField(
        max_length=200,
        verbose_name="Nome do Template",
        help_text="Nome descritivo do template HSM"
    )
    
    hsm_id = models.IntegerField(
        verbose_name="ID do HSM",
        help_text="ID do template HSM na Matrix"
    )
    
    cod_flow = models.IntegerField(
        verbose_name="Código do Flow",
        help_text="Código do flow de atendimento",
        null=True,
        blank=True
    )
    
    tipo_envio = models.IntegerField(
        choices=TIPO_ENVIO_CHOICES,
        default=1,
        verbose_name="Tipo de Envio",
        help_text="Tipo de envio do HSM"
    )
    
    descricao = models.TextField(
        verbose_name="Descrição",
        help_text="Descrição detalhada do template",
        blank=True
    )
    
    variaveis_descricao = models.JSONField(
        verbose_name="Descrição das Variáveis",
        help_text="Descrição das variáveis do HSM (ex: {'1': 'Nome do Cliente', '2': 'Valor'})",
        default=dict,
        blank=True
    )
    
    ativo = models.BooleanField(
        default=True,
        verbose_name="Ativo",
        help_text="Se este template está ativo"
    )
    
    data_criacao = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Data de Criação"
    )
    
    data_atualizacao = models.DateTimeField(
        auto_now=True,
        verbose_name="Data de Atualização"
    )
    
    class Meta:
        verbose_name = "Template HSM"
        verbose_name_plural = "Templates HSM"
        ordering = ['nome']
    
    def __str__(self):
        return f"{self.nome} (ID: {self.hsm_id})"
    
    def get_variaveis_descricao(self):
        """Retorna descrição das variáveis formatada"""
        if isinstance(self.variaveis_descricao, str):
            return json.loads(self.variaveis_descricao)
        return self.variaveis_descricao