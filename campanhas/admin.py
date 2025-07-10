from django.contrib import admin
from .models import TemplateSQL, CredenciaisHubsoft, ClienteConsultado, ConsultaExecucao, ConsultaCliente, CredenciaisBancoDados, MatrixAPIConfig, HSMTemplate

@admin.register(CredenciaisBancoDados)
class CredenciaisBancoDadosAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'tipo_banco', 'host', 'banco', 'ativo', 'data_criacao')
    list_filter = ('tipo_banco', 'ativo')
    search_fields = ('titulo', 'host', 'banco', 'usuario')
    readonly_fields = ('data_criacao', 'data_atualizacao')
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('titulo', 'tipo_banco', 'ativo')
        }),
        ('Conexão', {
            'fields': ('host', 'porta', 'banco')
        }),
        ('Credenciais', {
            'fields': ('usuario', 'senha')
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )

@admin.register(TemplateSQL)
class TemplateSQLAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'ativo', 'data_criacao', 'data_atualizacao')
    list_filter = ('ativo',)
    search_fields = ('titulo', 'descricao')
    readonly_fields = ('data_criacao', 'data_atualizacao')
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('titulo', 'descricao', 'ativo')
        }),
        ('Consulta SQL', {
            'fields': ('consulta_sql',)
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )

@admin.register(CredenciaisHubsoft)
class CredenciaisHubsoftAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'username', 'ativo', 'data_criacao', 'data_atualizacao')
    list_filter = ('ativo',)
    search_fields = ('titulo', 'username')
    readonly_fields = ('data_criacao', 'data_atualizacao')
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('titulo', 'ativo')
        }),
        ('Credenciais', {
            'fields': ('client_id', 'client_secret', 'username', 'password')
        }),
        ('URLs', {
            'fields': ('url_base', 'url_token')
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )

@admin.register(ClienteConsultado)
class ClienteConsultadoAdmin(admin.ModelAdmin):
    list_display = ('codigo_cliente', 'nome_razaosocial', 'telefone_corrigido', 'data_criacao')
    search_fields = ('codigo_cliente', 'nome_razaosocial', 'telefone_corrigido')
    readonly_fields = ('data_criacao', 'data_atualizacao')
    fieldsets = (
        ('Informações do Cliente', {
            'fields': ('codigo_cliente', 'nome_razaosocial', 'telefone_corrigido')
        }),
        ('Informações da Fatura', {
            'fields': ('id_fatura', 'vencimento_fatura', 'valor_fatura')
        }),
        ('Informações de Pagamento', {
            'fields': ('pix', 'codigo_barras', 'link_boleto')
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )

@admin.register(ConsultaExecucao)
class ConsultaExecucaoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'template_sql', 'status', 'total_registros_sql', 'total_consultados_api', 'total_erros', 'data_inicio', 'data_fim')
    list_filter = ('status', 'template_sql', 'credencial_hubsoft')
    search_fields = ('titulo',)
    readonly_fields = ('data_inicio', 'data_fim', 'total_registros_sql', 'total_consultados_api', 'total_erros')
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('titulo', 'template_sql', 'credencial_hubsoft', 'status')
        }),
        ('Estatísticas', {
            'fields': ('total_registros_sql', 'total_consultados_api', 'total_erros')
        }),
        ('Logs', {
            'fields': ('log_execucao',)
        }),
        ('Datas', {
            'fields': ('data_inicio', 'data_fim')
        }),
    )

@admin.register(ConsultaCliente)
class ConsultaClienteAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'execucao', 'sucesso_api', 'data_consulta')
    list_filter = ('sucesso_api', 'execucao')
    search_fields = ('cliente__nome_razaosocial', 'cliente__codigo_cliente')
    readonly_fields = ('data_consulta',)
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('execucao', 'cliente', 'sucesso_api')
        }),
        ('Dados', {
            'fields': ('dados_originais_sql', 'dados_api_response')
        }),
        ('Erro', {
            'fields': ('erro_api',)
        }),
        ('Datas', {
            'fields': ('data_consulta',)
        }),
    )

@admin.register(MatrixAPIConfig)
class MatrixAPIConfigAdmin(admin.ModelAdmin):
    list_display = ('nome', 'base_url', 'cod_conta', 'ativo', 'data_criacao')
    list_filter = ('ativo',)
    search_fields = ('nome', 'base_url')
    readonly_fields = ('data_criacao', 'data_atualizacao')
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('nome', 'ativo')
        }),
        ('Configurações da API', {
            'fields': ('base_url', 'api_key', 'cod_conta')
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )

@admin.register(HSMTemplate)
class HSMTemplateAdmin(admin.ModelAdmin):
    list_display = ('nome', 'hsm_id', 'tipo_envio', 'cod_flow', 'ativo', 'data_criacao')
    list_filter = ('tipo_envio', 'ativo')
    search_fields = ('nome', 'descricao')
    readonly_fields = ('data_criacao', 'data_atualizacao')
    
    def get_tipo_envio_display(self, obj):
        return dict(HSMTemplate.TIPO_ENVIO_CHOICES).get(obj.tipo_envio, obj.tipo_envio)
    get_tipo_envio_display.short_description = 'Tipo de Envio'
    
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('nome', 'descricao', 'ativo')
        }),
        ('Configurações HSM', {
            'fields': ('hsm_id', 'cod_flow', 'tipo_envio')
        }),
        ('Variáveis', {
            'fields': ('variaveis_descricao',),
            'description': 'Descrição das variáveis do HSM em formato JSON'
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )
