from django.core.cache import cache
from django.core.paginator import Paginator, EmptyPage
from django.core.urlresolvers import reverse
from django.http.response import HttpResponse
from django.shortcuts import render, redirect
from django.views.generic import View
from django_redis import get_redis_connection
from redis import StrictRedis

from apps.goods.models import GoodsCategory, IndexSlideGoods, IndexPromotion, IndexCategoryGoods, GoodsSKU
from apps.users.models import User
from apps.users.views import UserAddressView


class BaseCartView(View):

    def get_cart_count(self, request):
        """获取用户购物车中商品的总数量"""
        # todo: 读取用户添加到购物车中的商品总数量
        cart_count = 0  # 购物车商品总数量
        if request.user.is_authenticated():
            # 已经登录
            strict_redis = get_redis_connection()  # type: StrictRedis
            # cart_1 = {1: 2, 2 : 2}
            key = 'cart_%s' % request.user.id
            # 返回 list类型，存储的元素是 bytes
            # [2, 2]
            vals = strict_redis.hvals(key)
            for count in vals:  # count为bytes类型
                cart_count += int(count)

        return cart_count


class IndexView(BaseCartView):

    def get2(self, request):
        print(UserAddressView.__mro__)

        # 显示登录的用户名
        # 方式1：主动查询登录用户并显示
        # user_id = request.session.get('_auth_user_id')
        # user = User.objects.get(id=user_id)
        # context = {'user': user}
        # return render(request, 'index.html', context)

        # 方式2：使用django用户认证模块，直接显示
        # django会自动查询登录的用户对象，会保存到request对象中
        # 并且会把user对象传递给模块
        # user = request.user
        return render(request, 'index.html')

    def get(self, request):
        # 读取Redis中的缓存数据
        context = cache.get('index_page_data')
        if not context:
            print('没有缓存，从mysql数据库中读取')
            # 查询首页商品数据：商品类别，轮播图， 促销活动
            categories = GoodsCategory.objects.all()
            slide_skus = IndexSlideGoods.objects.all().order_by('index')
            promotions = IndexPromotion.objects.all().order_by('index')[0:2]
            # category_skus = IndexCategoryGoods.objects.all()

            for c in categories:
                # 查询当前类型所有的文字商品和图片商品
                text_skus = IndexCategoryGoods.objects.filter(
                    display_type=0, category=c)
                image_skus = IndexCategoryGoods.objects.filter(
                    display_type=1, category=c)[0:4]
                # 动态给对象新增实例属性
                c.text_skus = text_skus
                c.image_skus = image_skus

            # 定义要缓存的数据： 字典
            context = {
                'categories': categories,
                'slide_skus': slide_skus,
                'promotions': promotions,
            }

            # 缓存数据：保存数据到Redis中
            # 参数1： 键名
            # 参数2： 要缓存的数据（字典）
            # 参数3： 缓存时间：半个小时
            cache.set('index_page_data', context, 60*30)
        else:
            print('使用缓存')

        # 获取用户添加到购物车商品的总数量
        cart_count = self.get_cart_count(request)
        # cart_count = super().get_cart_count(request)

        # 定义模板显示的数据
        # 给字典新增一个键值
        context['cart_count'] = cart_count
        # context.update({'cart_count': cart_count})
        # context.update(cart_count=cart_count)

        # 响应请求
        return render(request, 'index.html', context)


class DetailView(BaseCartView):
    """商品详情界面"""

    def get(self, request, sku_id):
        """
        进入商品详情界面
        :param request:
        :param sku_id:  商品id
        :return:
        """

        # todo: 查询数据库数据
        # 查询商品SKU信息
        try:
            sku = GoodsSKU.objects.get(id=sku_id)
        except GoodsSKU.DoesNotExist:
            # 没有查询到商品跳转到首页
            return redirect(reverse('goods:index'))

        # 查询所有商品分类信息
        categories = GoodsCategory.objects.all()

        # 查询最新商品推荐(只查询两条)
        try:
            new_skus = GoodsSKU.objects.filter(
                category=sku.category).order_by('-create_time')[0:2]
        except:
            new_skus = None

        # 如果已登录，查询购物车信息
        cart_count = self.get_cart_count(request)

        # todo: 查询其他规格商品
        other_skus = GoodsSKU.objects.filter(
            spu=sku.spu).exclude(id=sku_id)

        # todo: 保存用户浏览的商品到Redis
        if request.user.is_authenticated():
            # 获取StrictRedis对象
            # strict_redis = StrictRedis()
            strict_redis = get_redis_connection()  # type: StrictRedis
            # history_1 = [3, 1, 2]
            key = 'history_%s' % request.user.id
            # 删除list中已存在的商品id
            strict_redis.lrem(key, 0, sku_id)
            # 添加商品id到List的左侧
            strict_redis.lpush(key, sku_id)
            # 控制元素的个数：最多只保存5个商品记录
            strict_redis.ltrim(key, 0, 4)

        context = {
            'sku': sku,
            'categories': categories,
            'new_skus': new_skus,
            'cart_count': cart_count,
            'other_skus': other_skus,
        }

        return render(request, 'detail.html', context)


class ListView(BaseCartView):

    def get(self, request, category_id, page_num):
        """
        显示商品列表界面
        :param request:
        :param category_id: 类别id
        :param page_num: 页码
        :return:
        """
        # 获取请求参数
        sort = request.GET.get('sort')

        # 校验参数合法性
        try:
            category = GoodsCategory.objects.get(id=category_id)
        except GoodsCategory.DoesNotExist:
            # 查询不到类别，跳转到首页
            # return redirect('/index')
            return redirect(reverse('goods:index'))

        # 业务：查询对应的商品数据
        # *商品分类信息
        categories = GoodsCategory.objects.all()
        # *新品推荐信息（在GoodsSKU表中，查询特定类别信息，按照时间倒序）
        try:
            new_skus = GoodsSKU.objects.filter(
                category=category).order_by('-create_time')[0:2]
        except:
            new_skus = None

        # 类别下所有的商品
        if sort == 'price':
            skus = GoodsSKU.objects.filter(category=category).order_by('price')  # 价格
        elif sort == 'hot':
            skus = GoodsSKU.objects.filter(category=category).order_by('-sales') # 销量
        else:  # default
            skus = GoodsSKU.objects.filter(category=category)                    # 默认排序
            sort = 'default'

        # todo: 商品分页信息
        # 参数1： 要分页的数据
        # 参数2： 每页显示多少条
        paginator = Paginator(skus, 2)
        try:
            page = paginator.page(page_num)
        except EmptyPage: # 页码出错
            # 出错，默认显示第一页
            page = paginator.page(1)

        # *购物车信息
        cart_count = self.get_cart_count(request)

        # 定义模板显示的数据
        context = {
            'category': category,
            'categories': categories,

            # 'skus': skus,
            'page': page,
            'page_range': paginator.page_range,

            'new_skus': new_skus,
            'cart_count': cart_count,
            'sort': sort,
        }

        # 响应请求
        return render(request, 'list.html', context)





































